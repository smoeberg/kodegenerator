"""Tests for the Redis task queue adapter and its memory fallback."""
from __future__ import annotations

import time

import pytest

from services.redis_task_queue import RedisTaskQueue


class Task:
    """Small WBS-compatible test task."""

    def __init__(self, task_id: str, *, dependencies: tuple[str, ...] = (), capabilities: tuple[str, ...] = (), priority: int = 0) -> None:
        self.id = task_id
        self.name = task_id
        self.dependencies = dependencies
        self.capabilities = capabilities
        self.priority = priority
        self.max_retries = 3
        self.metadata = {}


def test_enqueue_is_idempotent_and_claim_matches_capabilities() -> None:
    """A task is stored once and only a capable worker can claim it."""
    queue = RedisTaskQueue(lease_seconds=10)
    task = Task("t1", capabilities=("python",))

    assert queue.enqueue(task) == "t1"
    assert queue.enqueue(task) == "t1"
    assert queue.claim("worker-a", ["docker"]) is None
    claimed = queue.claim("worker-a", ["python", "docker"])
    assert claimed is not None
    assert claimed.task_id == "t1"
    assert claimed.agent_id == "worker-a"


def test_dependency_gate_blocks_until_dependency_is_completed() -> None:
    """Dependent work cannot be claimed before its dependency completes."""
    queue = RedisTaskQueue(lease_seconds=10)
    queue.enqueue(Task("a"))
    queue.enqueue(Task("b", dependencies=("a",)))

    first = queue.claim("worker-a")
    assert first is not None and first.task_id == "a"
    assert queue.claim("worker-b") is None

    queue.complete_task("a", "worker-a", {"patch": "A"})
    second = queue.claim("worker-b")
    assert second is not None and second.task_id == "b"


def test_ownership_is_enforced_and_completion_is_idempotent() -> None:
    """A different worker cannot mutate an active claim, and completion is safe."""
    queue = RedisTaskQueue(lease_seconds=10)
    queue.enqueue(Task("t1"))
    assert queue.claim("worker-a") is not None

    with pytest.raises(PermissionError):
        queue.heartbeat("t1", "worker-b")
    with pytest.raises(PermissionError):
        queue.complete_task("t1", "worker-b", {"bad": True})

    queue.complete_task("t1", "worker-a", {"ok": True})
    queue.complete_task("t1", "worker-a", {"ok": True})
    assert queue.claim("worker-b") is None


def test_expired_lease_is_recovered_for_another_worker() -> None:
    """An orphaned claim becomes available after its lease expires."""
    queue = RedisTaskQueue(lease_seconds=1)
    queue.enqueue(Task("t1"))
    assert queue.claim("worker-a") is not None

    time.sleep(1.05)
    assert queue.recover_orphans() == 1
    recovered = queue.claim("worker-b")
    assert recovered is not None
    assert recovered.task_id == "t1"
    assert recovered.agent_id == "worker-b"


def test_failure_retries_then_becomes_terminal_failure() -> None:
    """Retrying failures are requeued until the configured retry limit."""
    queue = RedisTaskQueue(lease_seconds=10)
    queue.enqueue(Task("t1"))

    for _ in range(3):
        claimed = queue.claim("worker-a")
        assert claimed is not None
        queue.fail_task("t1", "worker-a", "transient", retry=True)

    claimed = queue.claim("worker-a")
    assert claimed is not None
    queue.fail_task("t1", "worker-a", "terminal", retry=True)
    assert queue.claim("worker-b") is None
