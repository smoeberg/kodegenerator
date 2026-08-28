from __future__ import annotations

import pytest
from execution.pipeline_executors import ReleaseExecutor
from services.github_pr_contracts import GitHubConfig, PatchInfo, PRMetadata


class FakePublisher:
    def __init__(self, owner: str, repo: str, token: str, repo_root=None, config=None):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.repo_root = repo_root
        self.config = config
        self.published = []

    def publish_patch_pr(self, patch: PatchInfo, metadata: PRMetadata):
        self.published.append((patch, metadata))
        return {
            "pr_number": 42,
            "pr_url": f"https://github.com/{self.owner}/{self.repo}/pull/42",
            "branch": metadata.branch,
        }


def test_release_executor_publishes_pr_successfully():
    publisher_instance = None

    def factory(*args, **kwargs):
        nonlocal publisher_instance
        publisher_instance = FakePublisher(*args, **kwargs)
        return publisher_instance

    executor = ReleaseExecutor(publisher_factory=factory)
    payload = {
        "owner": "smoeberg",
        "repo": "kodegenerator",
        "token": "ghp_secret_token",
        "version": "1.0.0",
        "title": "Release 1.0.0",
        "description": "Changelog details",
        "base_branch": "main",
        "branch": "release/1.0.0",
        "labels": ["release"],
        "patch_content": "diff --git a/a.txt b/a.txt\n",
        "files_changed": ["a.txt"],
        "workflow_id": "wf-123",
    }

    result = executor.execute(payload)

    assert result["status"] == "success"
    assert result["release"]["component"] == "services/git_pr_publisher"
    assert result["release"]["pr_number"] == 42
    assert result["release"]["workflow_id"] == "wf-123"
    assert publisher_instance is not None
    assert publisher_instance.owner == "smoeberg"
    assert publisher_instance.repo == "kodegenerator"
    assert len(publisher_instance.published) == 1

    patch, meta = publisher_instance.published[0]
    assert patch.patch_content == "diff --git a/a.txt b/a.txt\n"
    assert meta.title == "Release 1.0.0"
    assert meta.branch == "release/1.0.0"


def test_release_executor_parses_repo_url_and_env_token(monkeypatch):
    publisher_instance = None

    def factory(*args, **kwargs):
        nonlocal publisher_instance
        publisher_instance = FakePublisher(*args, **kwargs)
        return publisher_instance

    monkeypatch.setenv("GITHUB_TOKEN", "env_token_val")
    executor = ReleaseExecutor(publisher_factory=factory)
    payload = {
        "repo_url": "https://github.com/smoeberg/kodegenerator.git",
        "version": "2.0.0",
    }

    result = executor.execute(payload)

    assert result["status"] == "success"
    assert publisher_instance.owner == "smoeberg"
    assert publisher_instance.repo == "kodegenerator"
    assert publisher_instance.token == "env_token_val"


def test_release_executor_fails_without_repo():
    executor = ReleaseExecutor(publisher_factory=FakePublisher)
    with pytest.raises(ValueError, match="release payload requires repo"):
        executor.execute({"token": "secret"})
