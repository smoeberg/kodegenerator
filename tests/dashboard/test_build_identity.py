from pathlib import Path

from dashboard.build_identity import (
    resolve_build_identity,
    source_fingerprint,
    write_build_metadata,
)


def test_source_fingerprint_tracks_source_but_ignores_local_metadata(tmp_path: Path) -> None:
    source = tmp_path / "dashboard" / "app.py"
    source.parent.mkdir()
    source.write_text("print('v1')\n", encoding="utf-8")

    first = source_fingerprint(tmp_path)
    (tmp_path / ".dor-build-revision").write_text("deadbeef\n", encoding="utf-8")
    (tmp_path / ".dor-build-fingerprint").write_text("ignored\n", encoding="utf-8")
    (tmp_path / ".env.demo").write_text("SECRET=local-only\n", encoding="utf-8")
    assert source_fingerprint(tmp_path) == first

    source.write_text("print('v2')\n", encoding="utf-8")
    assert source_fingerprint(tmp_path) != first


def test_resolve_build_identity_prefers_baked_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DOR_BUILD_REVISION", "env-revision")
    (tmp_path / ".dor-build-revision").write_text(
        "0123456789abcdef0123456789abcdef\n", encoding="utf-8"
    )
    (tmp_path / ".dor-build-fingerprint").write_text(
        "fedcba9876543210fedcba9876543210\n", encoding="utf-8"
    )

    identity = resolve_build_identity(tmp_path)

    assert identity.short_revision == "0123456789ab"
    assert identity.short_fingerprint == "fedcba987654"


def test_resolve_build_identity_uses_environment_revision_without_baked_revision(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DOR_BUILD_REVISION", "abcdef1234567890")
    (tmp_path / "source.py").write_text("VALUE = 1\n", encoding="utf-8")

    identity = resolve_build_identity(tmp_path)

    assert identity.short_revision == "abcdef123456"
    assert len(identity.fingerprint) == 64


def test_write_build_metadata_round_trips_without_git(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("VALUE = 1\n", encoding="utf-8")

    written = write_build_metadata(tmp_path, "cafebabedeadbeef")
    resolved = resolve_build_identity(tmp_path)

    assert resolved == written
    assert resolved.short_revision == "cafebabedead"
    assert len(resolved.fingerprint) == 64


def test_runtime_dockerfile_bakes_build_metadata() -> None:
    dockerfile = Path("docker/Dockerfile.runtime").read_text(encoding="utf-8")

    assert "ARG DOR_BUILD_REVISION=unknown" in dockerfile
    assert "python -m dashboard.build_identity" in dockerfile
    assert "--write-build-metadata /app" in dockerfile
    assert '--revision "${DOR_BUILD_REVISION}"' in dockerfile
