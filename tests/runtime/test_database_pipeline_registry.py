from sqlalchemy import create_engine

from infrastructure.persistence.models import Base, PipelineRuntimeStateModel
from infrastructure.runtime.queue import QueueMessageModel
from runtime.pipeline_registry import PipelineRegistry


class _Runtime:
    pass


def test_api_and_worker_registries_share_database_queue(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'shared.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[QueueMessageModel.__table__, PipelineRuntimeStateModel.__table__],
    )
    monkeypatch.setenv("DOR_QUEUE_BACKEND", "database")
    monkeypatch.setenv("DOR_PIPELINE_DATABASE_URL", database_url)
    monkeypatch.setenv("DOR_PIPELINE_STATE_ORGANIZATION_ID", "org-1")

    api_registry = PipelineRegistry(_Runtime())  # type: ignore[arg-type]
    worker_registry = PipelineRegistry(_Runtime())  # type: ignore[arg-type]
    api_registry.queue.enqueue_wbs_plan(
        [
            {
                "task_id": "shared-task",
                "name": "Shared task",
                "capabilities": ["pipeline.code"],
            }
        ]
    )

    claimed = worker_registry.queue.claim_next_task(
        "factory-worker@container-1", ["pipeline.code"]
    )

    assert claimed is not None
    assert claimed.task_id == "shared-task"
    assert (
        api_registry.queue.claim_next_task(
            "factory-worker@container-2", ["pipeline.code"]
        )
        is None
    )


def test_database_registries_isolate_organization_queues(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'tenants.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[QueueMessageModel.__table__, PipelineRuntimeStateModel.__table__],
    )
    monkeypatch.setenv("DOR_QUEUE_BACKEND", "database")
    monkeypatch.setenv("DOR_PIPELINE_DATABASE_URL", database_url)

    first = PipelineRegistry(_Runtime(), organization_id="org-1")  # type: ignore[arg-type]
    second = PipelineRegistry(_Runtime(), organization_id="org-2")  # type: ignore[arg-type]
    first.queue.enqueue_wbs_plan(
        [{"task_id": "same-id", "name": "First", "capabilities": ["code"]}]
    )
    second.queue.enqueue_wbs_plan(
        [{"task_id": "same-id", "name": "Second", "capabilities": ["code"]}]
    )

    first_claim = first.queue.claim_next_task("worker-1", ["code"])
    second_claim = second.queue.claim_next_task("worker-2", ["code"])

    assert first_claim is not None and first_claim.name == "First"
    assert second_claim is not None and second_claim.name == "Second"
