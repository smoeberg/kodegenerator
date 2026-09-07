"""Contract tests for canonical production image publishing."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/docker-publish.yml")
CANONICAL_DOCKERFILE = "docker/Dockerfile.runtime"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_publish_workflow_uses_canonical_runtime_dockerfile() -> None:
    text = _workflow_text()
    assert f"file: {CANONICAL_DOCKERFILE}" in text
    assert "file: Dockerfile" not in text


def test_publish_workflow_binds_build_identity_to_exact_sha() -> None:
    text = _workflow_text()
    assert "DOR_BUILD_REVISION=${{ github.sha }}" in text


def test_publish_workflow_requires_immutable_digest_output() -> None:
    text = _workflow_text()
    assert "id: build" in text
    assert "${{ steps.build.outputs.digest }}" in text
    assert "sha256:*" in text
