"""Security regression coverage for repository-controlled Compose deployments."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from execution.pipeline_executors import DockerDeployService, _validate_compose_policy


class RecordingRunner:
    def __init__(self, *, fail_first_compose: bool = False) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.fail_first_compose = fail_first_compose
        self.compose_calls = 0

    def __call__(self, argv, **kwargs):
        command = list(argv)
        self.calls.append((command, kwargs))
        stdout = ""
        returncode = 0
        stderr = ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "abcdef1234567890\n"
        if command[:2] == ["docker", "compose"]:
            self.compose_calls += 1
            if self.fail_first_compose and self.compose_calls == 1:
                returncode = 1
                stderr = "simulated deploy failure"
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _workspace(tmp_path, compose_text: str) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(compose_text, encoding="utf-8")


def _compose_calls(runner: RecordingRunner):
    return [call for call in runner.calls if call[0][:2] == ["docker", "compose"]]


def test_compose_subprocess_receives_only_minimal_allowlisted_environment(
    tmp_path, monkeypatch
) -> None:
    _workspace(
        tmp_path,
        "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n",
    )
    monkeypatch.setenv("DOR_JWT_SIGNING_KEYS", "jwt-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("DOR_AUTHORITY_SIGNING_KEY", "authority-secret")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "minio-secret")
    monkeypatch.setenv("HOME", "/sensitive/home")

    runner = RecordingRunner()
    result = DockerDeployService(runner=runner).deploy(
        repository="https://github.test/demo.git",
        project_name="demo",
        environment="test",
        target="docker-compose.yml",
        release="v1.2.3",
        workspace=str(tmp_path),
    )

    assert result["image_tag"] == "demo:test-abcdef123456"
    compose_calls = _compose_calls(runner)
    assert len(compose_calls) == 1
    assert compose_calls[0][1]["env"] == {
        "PATH": os.defpath,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "DOR_IMAGE_TAG": "demo:test-abcdef123456",
    }
    for secret_name in (
        "DOR_JWT_SIGNING_KEYS",
        "DATABASE_URL",
        "DOR_AUTHORITY_SIGNING_KEY",
        "MINIO_ROOT_PASSWORD",
        "HOME",
    ):
        assert secret_name not in compose_calls[0][1]["env"]


def test_rollback_compose_subprocess_is_equally_isolated(tmp_path, monkeypatch) -> None:
    _workspace(
        tmp_path,
        "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n",
    )
    monkeypatch.setenv("DOR_PIPELINE_ROLLBACK_IMAGE", "demo:known-good")
    monkeypatch.setenv("DOR_JWT_SIGNING_KEYS", "must-not-leak")

    runner = RecordingRunner(fail_first_compose=True)
    with pytest.raises(RuntimeError, match="deployment failed"):
        DockerDeployService(runner=runner).deploy(
            repository="https://github.test/demo.git",
            project_name="demo",
            environment="test",
            target="docker-compose.yml",
            release="v1.2.3",
            workspace=str(tmp_path),
        )

    compose_calls = _compose_calls(runner)
    assert len(compose_calls) == 2
    assert compose_calls[0][1]["env"] == {
        "PATH": os.defpath,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "DOR_IMAGE_TAG": "demo:test-abcdef123456",
    }
    assert compose_calls[1][1]["env"] == {
        "PATH": os.defpath,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "DOR_IMAGE_TAG": "demo:known-good",
    }
    assert "DOR_JWT_SIGNING_KEYS" not in compose_calls[1][1]["env"]


@pytest.mark.parametrize(
    "variable",
    [
        "DOR_JWT_SIGNING_KEYS",
        "DATABASE_URL",
        "DOR_AUTHORITY_SIGNING_KEY",
        "MINIO_ROOT_PASSWORD",
    ],
)
def test_compose_policy_rejects_nonallowlisted_environment_interpolation(
    tmp_path, variable
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        f"services:\n  app:\n    image: ${{DOR_IMAGE_TAG}}\n"
        f"    environment:\n      LEAKED_SECRET: ${{{variable}}}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-allowlisted environment variables"):
        _validate_compose_policy(compose)


def test_compose_policy_rejects_plain_dollar_variable_form(tmp_path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n"
        "    environment:\n      LEAKED_SECRET: $DATABASE_URL\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DATABASE_URL"):
        _validate_compose_policy(compose)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("    build: .\n", "repository-controlled build"),
        ("    env_file: /proc/1/environ\n", "env_file access"),
    ],
)
def test_compose_policy_rejects_additional_host_read_surfaces(
    tmp_path, extra, message
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n" + extra,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        _validate_compose_policy(compose)


def test_compose_policy_rejects_file_backed_secrets_and_configs(tmp_path) -> None:
    for section in ("secrets", "configs"):
        compose = tmp_path / f"{section}.yml"
        compose.write_text(
            "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n"
            f"{section}:\n  stolen:\n    file: /proc/1/environ\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="host file access"):
            _validate_compose_policy(compose)


def test_compose_policy_accepts_image_only_compose(tmp_path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  app:\n    image: ${DOR_IMAGE_TAG}\n"
        "    cap_drop:\n      - ALL\n"
        "    security_opt:\n      - no-new-privileges:true\n",
        encoding="utf-8",
    )

    _validate_compose_policy(compose)
