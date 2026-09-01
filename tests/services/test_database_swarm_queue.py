from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.models import Base
from infrastructure.runtime.queue import DatabaseQueue, QueueMessageModel
from services.database_swarm_queue import DatabaseSwarmTaskQueue
from services.swarm_task_queue import QueuedTaskStatus


def _queue(tmp_path) -> DatabaseSwarmTaskQueue:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queue.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine, tables=[QueueMessageModel.__table__])
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return DatabaseSwarmTaskQueue(
        DatabaseQueue(sessions, organization_id="org-1", lease_seconds=30)
    )


def test_database_swarm_queue_enforces_dependencies_and_replays_plan(tmp_path) -> None:
    queue = _queue(tmp_path)
    plan = [
        {"task_id": "a", "name": "A", "capabilities": ["pipeline.code"]},
        {
            "task_id": "b",
            "name": "B",
            "dependencies": ["a"],
            "capabilities": ["pipeline.tests"],
        },
    ]

    assert queue.enqueue_wbs_plan(plan) == 2
    assert queue.enqueue_wbs_plan(plan) == 0
    assert queue.claim_next_task("tester", ["pipeline.tests"]) is None
    first = queue.claim_next_task("coder", ["pipeline.code"])
    assert first is not None and first.task_id == "a"
    queue.complete_task("a", "coder", {"commit": "abc"})
    second = queue.claim_next_task("tester", ["pipeline.tests"])
    assert second is not None and second.task_id == "b"
    queue.complete_task("b", "tester", {"passed": True})
    assert queue.get_task("b").status is QueuedTaskStatus.COMPLETED


def test_two_workers_cannot_claim_same_database_task(tmp_path) -> None:
    queue = _queue(tmp_path)
    queue.enqueue_wbs_plan(
        [{"task_id": "only", "name": "Only", "capabilities": ["pipeline.code"]}]
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda worker: queue.claim_next_task(worker, ["pipeline.code"]),
                ["worker-a", "worker-b"],
            )
        )

    assert sum(item is not None for item in claims) == 1


def test_stale_worker_cannot_complete_after_lease_reassignment(tmp_path) -> None:
    queue = _queue(tmp_path)
    queue.enqueue_wbs_plan([{"task_id": "task", "name": "Task"}])
    first = queue.claim_next_task("worker-a", [])
    assert first is not None
    message = queue._queue.get("swarm:task")
    assert message is not None and message.lease_id
    queue._queue.fail(
        message.id, "worker-a", message.lease_id, "retry", retry_after_seconds=0
    )
    second = queue.claim_next_task("worker-b", [])
    assert second is not None

    try:
        queue.complete_task("task", "worker-a", {})
    except PermissionError:
        pass
    else:
        raise AssertionError("stale worker completed a reassigned task")
