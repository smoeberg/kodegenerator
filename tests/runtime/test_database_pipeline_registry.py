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
    assert api_registry.queue.claim_next_task(
        "factory-worker@container-2", ["pipeline.code"]
    ) is None
