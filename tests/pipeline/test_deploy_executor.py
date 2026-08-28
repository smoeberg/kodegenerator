from __future__ import annotations

from types import SimpleNamespace

from execution.pipeline_executors import DeployExecutor, DockerDeployService


class FakeDeployBackend:
    def __init__(self):
        self.calls = []

    def deploy(self, repository, project_name, environment, target, release=None, workspace=None):
        self.calls.append((repository, project_name, environment, target, release, workspace))
        return {"deployed_at": "2026-08-28T00:00:00+00:00", "image_tag": "registry/demo:prod-abc123", "url": "https://demo.example"}


def test_deploy_executor_is_injectable():
    backend = FakeDeployBackend()
    result = DeployExecutor(backend).execute({
        "repository": "https://github.com/example/demo.git",
        "project_name": "demo",
        "environment": "prod",
        "target": "docker-compose.yml",
        "release": "v1.2.3",
        "workspace": "/tmp/demo",
    })
    assert result["status"] == "success"
    assert result["deployment"]["image_tag"] == "registry/demo:prod-abc123"
    assert backend.calls[0][4] == "v1.2.3"


def test_deploy_executor_rejects_missing_repository():
    try:
        DeployExecutor(FakeDeployBackend()).execute({"project_name": "demo", "target": "docker"})
    except ValueError as exc:
        assert "repository" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_docker_service_checks_out_builds_pushes_and_composes(monkeypatch, tmp_path):
    calls = []
    responses = {
        ("git", "describe", "--tags", "--abbrev=0"): SimpleNamespace(returncode=0, stdout="v1.2.3\n", stderr=""),
        ("git", "rev-parse", "HEAD"): SimpleNamespace(returncode=0, stdout="abcdef1234567890\n", stderr=""),
    }

    def runner(command, **kwargs):
        calls.append(command)
        return responses.get(tuple(command), SimpleNamespace(returncode=0, stdout="", stderr=""))

    monkeypatch.setenv("DOR_PIPELINE_DOCKER_REGISTRY", "registry.example")
    service = DockerDeployService(runner=runner)
    (tmp_path / ".git").mkdir()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    result = service.deploy("https://github.com/example/demo.git", "Demo", "prod", "docker-compose.yml", workspace=str(tmp_path))

    assert result["commit_sha"] == "abcdef1234567890"
    assert result["image_tag"] == "registry.example/demo:prod-abcdef123456"
    assert any(c[:3] == ["docker", "build", "-t"] for c in calls)
    assert [c[0:2] for c in calls if c[0] == "docker"] == [["docker", "build"], ["docker", "push"], ["docker", "compose"]]


def test_docker_service_reports_deploy_failure_and_attempts_rollback(monkeypatch, tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "compose", "-f"] and "up" in command:
            if kwargs["env"]["DOR_IMAGE_TAG"] == "registry.example/demo:prod-oldimage":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        if command[:2] == ["git", "describe"]:
            return SimpleNamespace(returncode=0, stdout="v1.2.3\n", stderr="")
        if command[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout="abcdef1234567890\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("DOR_PIPELINE_DOCKER_REGISTRY", "registry.example")
    monkeypatch.setenv("DOR_PIPELINE_ROLLBACK_IMAGE", "registry.example/demo:prod-oldimage")
    service = DockerDeployService(runner=runner)
    (tmp_path / ".git").mkdir()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")

    try:
        service.deploy("repo", "demo", "prod", "docker-compose.yml", workspace=str(tmp_path))
    except RuntimeError as exc:
        assert "deployment failed" in str(exc)
        assert "rollback=attempted" in str(exc)
    else:
        raise AssertionError("expected deployment failure")

    assert sum(c[:3] == ["docker", "compose", "-f"] for c in calls) == 2
