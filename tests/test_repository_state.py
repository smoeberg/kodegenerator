from pathlib import Path

from scripts.repository_state import (
    inspect_repository,
    load_contract,
    migration_heads,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_tracked_repository_state_matches_canonical_runtime() -> None:
    contract = load_contract(ROOT)
    report = inspect_repository(ROOT, "HEAD")

    assert report["classification"] == "VERIFIED"
    assert report["head_sha"]
    assert report["base_sha"]
    assert validate_contract(ROOT, contract, report) == []


def test_migration_graph_has_exact_declared_head() -> None:
    contract = load_contract(ROOT)

    assert migration_heads(ROOT) == [contract["canonical_alembic_head"]]


def test_canonical_release_metadata_is_explicit() -> None:
    contract = load_contract(ROOT)

    assert contract["canonical_version"] == "1.4.0"
    assert contract["canonical_runtime_dockerfile"] == "docker/Dockerfile.runtime"
    assert ".github/workflows/phase7.yml" in contract["required_workflows"]
    assert ".github/workflows/docker-publish.yml" in contract["required_workflows"]


def _write_contract_fixture(root: Path, *, readme_version: str = "1.4.0", publish_file: str = "docker/Dockerfile.runtime") -> tuple[dict, dict]:
    (root / "api").mkdir(parents=True)
    (root / "docker").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "phase4" / "implementation_agent").mkdir(parents=True)

    (root / "README.md").write_text(
        f"# DOR\n\n**Version:** {readme_version}\n",
        encoding="utf-8",
    )
    (root / "api" / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI(version="1.4.0")\n',
        encoding="utf-8",
    )
    (root / "docker" / "Dockerfile.runtime").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (root / "compose.yml").write_text(
        "x-runtime-service:\n  build:\n    dockerfile: docker/Dockerfile.runtime\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "docker-publish.yml").write_text(
        "\n".join(
            (
                "file: " + publish_file,
                "DOR_BUILD_REVISION=${{ github.sha }}",
                "Verify published image digest",
                "case \"${IMAGE_DIGEST}\" in",
                "  sha256:*) ;;",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "phase4" / "implementation_agent" / "ARCHITECTURE.md").write_text(
        "The governed runtime uses the Phase 6 `BubblewrapToolRunner` by default.\n",
        encoding="utf-8",
    )

    contract = {
        "canonical_alembic_head": "032_work_unit_revisions",
        "canonical_branch": "main",
        "canonical_version": "1.4.0",
        "canonical_runtime_dockerfile": "docker/Dockerfile.runtime",
        "canonical_runtime_paths": [],
        "required_workflows": [],
        "agent_protocol": "",
    }
    report = {"alembic_heads": ["032_work_unit_revisions"]}
    return contract, report


def test_repository_contract_detects_version_drift(tmp_path: Path) -> None:
    contract, report = _write_contract_fixture(tmp_path, readme_version="9.9.9")

    errors = validate_contract(tmp_path, contract, report)

    assert "README version mismatch" in "\n".join(errors)


def test_repository_contract_detects_noncanonical_publish_dockerfile(tmp_path: Path) -> None:
    contract, report = _write_contract_fixture(tmp_path, publish_file="Dockerfile")

    errors = validate_contract(tmp_path, contract, report)

    assert "does not publish the canonical runtime Dockerfile" in "\n".join(errors)


def test_agent_protocol_forbids_memory_as_repository_evidence() -> None:
    protocol = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Memory is historical context, never evidence" in protocol
    assert "git fetch origin --prune" in protocol
    assert "VERIFIED" in protocol
    assert "UNKNOWN" in protocol


def test_supported_agent_bootstraps_share_one_canonical_protocol() -> None:
    for relative_path in (
        "CLAUDE.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
    ):
        bootstrap = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "AGENTS.md" in bootstrap
        assert "git fetch origin --prune" in bootstrap
        assert "scripts/repository_state.py" in bootstrap
