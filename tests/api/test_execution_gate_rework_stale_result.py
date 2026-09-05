"""Fail-closed regression for late rework worker results."""

from datetime import datetime, timezone

from domain.pipeline_gates import get_pipeline_gates
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from domain.workflow import Workflow
from runtime.pipeline_orchestrator import PipelineOrchestrator


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


def test_stale_rework_result_cannot_overwrite_newer_workflow_context() -> None:
    orch = PipelineOrchestrator(RuntimeStub(), state_store=MemoryStore())
    now = datetime.now(timezone.utc)
    workflow = Workflow(
        id="wf-stale-rework",
        name="Stale rework result",
        current_state=PipelineState.ARCHITECTURE_GENERATED,
        states=list(PipelineState),
        transitions=get_pipeline_transitions(),
        gates=get_pipeline_gates(),
        context={
            "organization_id": "org-1",
            "architecture": {"revision": 2, "source": "newer-round"},
        },
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
    request = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="This worker will return after governance has moved on.",
    )
    task = orch.list_tasks(workflow.id)[0]
    task.result = {"architecture": {"revision": 1, "source": "stale-worker"}}

    # A newer governance round exists before the old worker reports completion.
    orch._set_gate_round(workflow, gate_id, 2)
    next(item for item in workflow.gates if item.id == gate_id).decision_id = None
    orch.handle_task_completion(task)

    assert workflow.context["architecture"] == {
        "revision": 2,
        "source": "newer-round",
    }
    assert orch.get_gate_round(workflow.id, gate_id) == 2
    assert orch.get_gate_decision(workflow.id, gate_id) is None
    record = workflow.context["gate_rework_history"][0]
    assert record["task_id"] == request["task_id"]
    assert record["status"] == "stale_completion"
    assert "to_round" not in record
