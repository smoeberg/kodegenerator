from __future__ import annotations

from types import SimpleNamespace

from services.pipeline_worker import PipelineExecutorSynthesizer
from services.swarm_task_queue import QueuedTask


class CapturingExecutor:
    def __init__(self) -> None:
        self.payload = None

    def execute(self, payload):
        self.payload = payload
        return {"status": "success"}


def test_pipeline_worker_resolves_latest_context_at_claim_time() -> None:
    executor = CapturingExecutor()
    workflow = SimpleNamespace(
        context={"contracts": {"fingerprint": "current"}},
        metadata={"organization_id": "org-1", "created_by": "actor-1"},
    )
    orchestrator = SimpleNamespace(_get_workflow=lambda workflow_id: workflow)
    task = QueuedTask(
        task_id="task-1",
        name="generate_tests",
        metadata={
            "task_type": "generate_tests",
            "workflow_id": "workflow-1",
            "execution_parameters": {
                "context": {"contracts": {"fingerprint": "stale"}}
            },
        },
    )

    result = PipelineExecutorSynthesizer(
        orchestrator, {"generate_tests": executor}
    ).synthesize(task)

    assert result == {"status": "success"}
    assert executor.payload["context"]["contracts"]["fingerprint"] == "current"
    assert executor.payload["organization_id"] == "org-1"
    assert executor.payload["actor_id"] == "actor-1"
