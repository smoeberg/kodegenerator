"""Two-worker proofs for deploy and PR publication idempotency."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from execution.pipeline_executors import DeployExecutor, ReleaseExecutor
from infrastructure.persistence.models import Base
from infrastructure.persistence.side_effect_store import SQLAlchemySideEffectStore
from services.side_effects import SideEffectCoordinator, SideEffectInProgressError


@pytest.fixture
def coordinator(tmp_path) -> SideEffectCoordinator:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'side-effects.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return SideEffectCoordinator(SQLAlchemySideEffectStore(sessions, lease_seconds=60))


def deploy_grant() -> MagicMock:
    grant = MagicMock()
    grant.verified = True
    grant.action = "pipeline.deploy"
    grant.resource = "repo"
    grant.parameters = (
        ("environment", "prod"),
        ("target", "docker-compose.yml"),
        ("release", "v1"),
    )
    return grant


class BlockingDeployBackend:
    """Represent Docker build, push and Compose as one terminal execution."""

    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def deploy(self, *args, **kwargs):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        return {
            "image_tag": "registry/app:prod-abc",
            "url": "https://app.example",
            "deployed_at": "2026-08-28T00:00:00+00:00",
        }


def test_two_workers_produce_one_image_and_one_deployment(coordinator) -> None:
    backend = BlockingDeployBackend()
    first = DeployExecutor(backend, side_effects=coordinator)
    second = DeployExecutor(backend, side_effects=coordinator)
    payload = {
        "task_id": "task-deploy-1",
        "organization_id": "org-1",
        "repository": "repo",
        "project_name": "app",
        "environment": "prod",
        "target": "docker-compose.yml",
        "release": "v1",
        "authority_grant": deploy_grant(),
    }
    outcome: list[dict] = []
    worker = threading.Thread(target=lambda: outcome.append(first.execute(payload)))
    worker.start()
    assert backend.entered.wait(timeout=5)

    with pytest.raises(SideEffectInProgressError, match="already in progress"):
        second.execute(payload)
    backend.release.set()
    worker.join(timeout=5)

    replay = second.execute(payload)
    assert backend.calls == 1
    assert outcome[0]["deployment"]["replayed"] is False
    assert replay["deployment"]["replayed"] is True
    assert replay["deployment"]["image_tag"] == "registry/app:prod-abc"


class BlockingPublisher:
    calls = 0
    entered = threading.Event()
    release = threading.Event()

    def __init__(self, **kwargs) -> None:
        pass

    def publish_patch_pr(self, patch, metadata):
        type(self).calls += 1
        type(self).entered.set()
        assert type(self).release.wait(timeout=5)
        return {
            "pr_number": 42,
            "pr_url": "https://github.com/acme/app/pull/42",
            "branch": metadata.branch,
        }


def test_two_workers_publish_one_pull_request(coordinator) -> None:
    BlockingPublisher.calls = 0
    BlockingPublisher.entered = threading.Event()
    BlockingPublisher.release = threading.Event()
    first = ReleaseExecutor(
        publisher_factory=BlockingPublisher, side_effects=coordinator
    )
    second = ReleaseExecutor(
        publisher_factory=BlockingPublisher, side_effects=coordinator
    )
    payload = {
        "task_id": "task-release-1",
        "organization_id": "org-1",
        "owner": "acme",
        "repo": "app",
        "token": "never-persist-this",
        "version": "1.0.0",
        "patch_content": "diff --git a/a b/a\n",
    }
    outcome: list[dict] = []
    worker = threading.Thread(target=lambda: outcome.append(first.execute(payload)))
    worker.start()
    assert BlockingPublisher.entered.wait(timeout=5)

    with pytest.raises(SideEffectInProgressError, match="already in progress"):
        second.execute(payload)
    BlockingPublisher.release.set()
    worker.join(timeout=5)

    replay = second.execute(payload)
    assert BlockingPublisher.calls == 1
    assert outcome[0]["release"]["replayed"] is False
    assert replay["release"]["replayed"] is True
    assert replay["release"]["pr_number"] == 42


def test_failed_side_effect_can_be_retried(coordinator) -> None:
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary")
        return {"ok": True}

    with pytest.raises(TimeoutError):
        coordinator.execute(
            organization_id="org-1",
            action="release.publish",
            idempotency_key="retry-1",
            request_data={"release": "v1"},
            operation=operation,
        )
    result, replayed = coordinator.execute(
        organization_id="org-1",
        action="release.publish",
        idempotency_key="retry-1",
        request_data={"release": "v1"},
        operation=operation,
    )
    assert result == {"ok": True}
    assert replayed is False
    assert attempts == 2
