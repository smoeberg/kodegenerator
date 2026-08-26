from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from services.swarm_task_queue import QueuedTaskStatus, SwarmTaskQueue


@dataclass
class FakeTask:
    id: str
    name: str
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class FakePlan:
    id: str
    tasks: list[FakeTask]


class ManualClock:
    def __init__(self):
        self.now = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: int):
        self.now += timedelta(seconds=seconds)


def task(task_id, dependencies=(), capabilities=("code",)):
    return FakeTask(task_id, task_id, list(dependencies), list(capabilities))


def test_parallel_claiming_has_no_race_and_claims_each_task_once():
    queue = SwarmTaskQueue(lease_seconds=60)
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task(f"T{i}") for i in range(20)]))

    def claim(i):
        return queue.claim_next_task(f"agent-{i}", ["code"])

    with ThreadPoolExecutor(max_workers=20) as pool:
        claimed = list(pool.map(claim, range(20)))

    ids = [item.task_id for item in claimed if item is not None]
    assert len(ids) == 20
    assert len(set(ids)) == 20
    assert queue.pending_count() == 0


def test_enqueue_is_idempotent_for_same_plan():
    queue = SwarmTaskQueue()
    plan = FakePlan("plan-1", [task("T1"), task("T2")])
    assert queue.enqueue_wbs_plan(plan) == 2
    assert queue.enqueue_wbs_plan(plan) == 0


def test_dependencies_block_claim_until_all_dependencies_completed():
    queue = SwarmTaskQueue()
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("A"), task("B", ["A"]), task("C", ["A", "B"])]))

    first = queue.claim_next_task("agent-a", ["code"])
    assert first and first.task_id == "A"
    assert queue.claim_next_task("agent-b", ["code"]) is None

    queue.complete_task("A", "agent-a", {"patch": "a"})
    second = queue.claim_next_task("agent-b", ["code"])
    assert second and second.task_id == "B"
    assert queue.claim_next_task("agent-c", ["code"]) is None

    queue.complete_task("B", "agent-b", {"patch": "b"})
    third = queue.claim_next_task("agent-c", ["code"])
    assert third and third.task_id == "C"


def test_lease_timeout_releases_task_for_another_agent():
    clock = ManualClock()
    queue = SwarmTaskQueue(lease_seconds=300, clock=clock)
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("T1")]))

    claimed = queue.claim_next_task("crashed-agent", ["code"])
    assert claimed is not None
    clock.advance(301)

    recovered = queue.claim_next_task("replacement-agent", ["code"])
    assert recovered is not None
    assert recovered.task_id == "T1"
    assert recovered.agent_id == "replacement-agent"


def test_heartbeat_extends_lease():
    clock = ManualClock()
    queue = SwarmTaskQueue(lease_seconds=300, clock=clock)
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("T1")]))
    queue.claim_next_task("agent", ["code"])

    clock.advance(240)
    queue.heartbeat("T1", "agent")
    clock.advance(100)
    recovered = queue.claim_next_task("other", ["code"])
    assert recovered is None


def test_expired_worker_cannot_complete_after_reclaim():
    clock = ManualClock()
    queue = SwarmTaskQueue(lease_seconds=10, clock=clock)
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("T1")]))
    queue.claim_next_task("agent-a", ["code"])
    clock.advance(11)

    queue.claim_next_task("agent-b", ["code"])
    with pytest.raises(PermissionError):
        queue.complete_task("T1", "agent-a", {"patch": "stale"})


def test_capabilities_are_required_for_claim():
    queue = SwarmTaskQueue()
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("T1", capabilities=("security",))]))
    assert queue.claim_next_task("developer", ["code"]) is None
    claimed = queue.claim_next_task("security-agent", ["security", "code"])
    assert claimed is not None


def test_failure_can_retry_and_eventually_be_terminal():
    queue = SwarmTaskQueue()
    queue.enqueue_wbs_plan(FakePlan("plan-1", [task("T1")]))
    queue.claim_next_task("agent", ["code"])
    queue.fail_task("T1", "agent", "temporary", retry=True)
    assert queue.get_task("T1").status == QueuedTaskStatus.PENDING

    queue.claim_next_task("agent", ["code"])
    queue.fail_task("T1", "agent", "permanent", retry=False)
    assert queue.get_task("T1").status == QueuedTaskStatus.FAILED
