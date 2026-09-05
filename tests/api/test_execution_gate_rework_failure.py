"""Worker failure semantics for governed gate rework."""

from datetime import datetime, timezone

from domain.pipeline_gates import get_pipeline_gates
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from domain.task import TaskStatus
from domain.workflow import Workflow
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import PipelineAwareQueue
from services.swarm_task_queue import QueuedTaskStatus, SwarmTaskQueue


class MemoryStore:
    def __init__(self) -> None:
        self.snapshot = None

    def save(self, snapshot) -> None:
        self.snapshot = snapshot

    def load(self):
        return self.snapshot


class RuntimeStub:
    def get_workflow(self, *args):
        return None


def test_rework_failure_tracks_queue_retry_then_allows_fresh_attempt() -> None:
    store = MemoryStore()
    raw_queue = SwarmTaskQueue(lease_seconds=60)
    orch = PipelineOrchestrator(
        RuntimeStub(),
        task_queue=raw_queue,
        state_store=store,
    )
    now = datetime.now(timezone.utc)
    workflow = Workflow(
        id="wf-rework-failure",
        name="Rework failure semantics",
        current_state=PipelineState.ARCHITECTURE_GENERATED,
        states=list(PipelineState),
        transitions=get_pipeline_transitions(),
        gates=get_pipeline_gates(),
        context={"organization_id": "org-1"},
        metadata={"organization_id": "org-1", "created_by": "owner"},
        created_at=now,
        updated_at=now,
    )
    orch._workflows[workflow.id] = workflow
    gate_id = "gate_architecture_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="controller",
        decision="rejected",
    )
    first = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Regenerate architecture.",
    )
    aware_queue = PipelineAwareQueue(raw_queue, orch)

    claimed = aware_queue.claim_next_task("worker-1", [])
    assert claimed is not None
    assert claimed.task_id == first["task_id"]
    aware_queue.fail_task(
        claimed.task_id,
        "worker-1",
        "transient provider error",
        retry=True,
    )

    domain_task = orch._tasks[first["task_id"]]
    assert raw_queue.get_task(first["task_id"]).status == QueuedTaskStatus.PENDING
    assert domain_task.status == TaskStatus.RETRYING
    assert domain_task.retry_count == 1
    assert domain_task.last_error == "transient provider error"
    assert orch.get_gate_rework_status(workflow.id, gate_id)["active"] is True
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"
    assert workflow.context["gate_rework_history"][0]["status"] == "retrying"
    assert workflow.context["gate_rework_history"][0]["error"] == "transient provider error"
    assert store.snapshot["tasks"][first["task_id"]]["status"] == TaskStatus.RETRYING.value

    claimed = aware_queue.claim_next_task("worker-2", [])
    assert claimed is not None
    assert claimed.task_id == first["task_id"]
    aware_queue.fail_task(
        claimed.task_id,
        "worker-2",
        "permanent architecture error",
        retry=False,
    )

    domain_task = orch._tasks[first["task_id"]]
    assert raw_queue.get_task(first["task_id"]).status == QueuedTaskStatus.FAILED
    assert domain_task.status == TaskStatus.FAILED
    assert orch.get_gate_rework_status(workflow.id, gate_id)["active"] is False
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"
    assert orch.get_gate_round(workflow.id, gate_id) == 1
    assert workflow.context["gate_rework_history"][0]["status"] == "failed"
    assert workflow.context["gate_rework_history"][0]["error"] == "permanent architecture error"

    second = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Retry with corrected upstream inputs.",
    )
    assert second["attempt"] == 2
    assert second["task_id"] != first["task_id"]
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"
    assert orch.get_gate_round(workflow.id, gate_id) == 1
