"""Regression tests for governed upstream rework of rejected execution gates."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import execution as execution_api
from api.endpoints.execution import GateReworkRequest
from domain.pipeline_gates import get_pipeline_gates
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from domain.task import TaskStatus
from domain.workflow import Workflow
from runtime.pipeline_orchestrator import PipelineOrchestrator


class MemoryStore:
    def __init__(self) -> None:
        self.snapshot = None

    def save(self, snapshot):
        self.snapshot = snapshot

    def load(self):
        return self.snapshot


class RuntimeStub:
    def get_workflow(self, *args):
        return None


class QueueStub:
    def __init__(self) -> None:
        self.submitted = []

    def submit_task(self, task) -> None:
        self.submitted.append(task)


def build_orchestrator(
    state: PipelineState = PipelineState.ARCHITECTURE_GENERATED,
    *,
    queue: QueueStub | None = None,
    store: MemoryStore | None = None,
) -> tuple[PipelineOrchestrator, Workflow]:
    state_store = store or MemoryStore()
    orch = PipelineOrchestrator(RuntimeStub(), task_queue=queue, state_store=state_store)
    now = datetime.now(timezone.utc)
    workflow = Workflow(
        id="wf-rework-001",
        name="Gate rework semantics",
        current_state=state,
        states=list(PipelineState),
        transitions=get_pipeline_transitions(),
        gates=get_pipeline_gates(),
        context={"organization_id": "org-1"},
        metadata={"organization_id": "org-1", "created_by": "owner"},
        created_at=now,
        updated_at=now,
    )
    orch._workflows[workflow.id] = workflow
    return orch, workflow


def reject(orch: PipelineOrchestrator, workflow: Workflow, gate_id: str) -> None:
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="controller",
        decision="rejected",
    )


def test_architecture_rework_queues_canonical_task_but_keeps_rejection() -> None:
    queue = QueueStub()
    orch, workflow = build_orchestrator(queue=queue)
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)

    result = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Architecture must include the revised trust boundary.",
    )

    assert result["gate_id"] == gate_id
    assert result["round"] == 1
    assert result["decision"] == "rejected"
    assert result["blocking"] is True
    assert result["workflow_advanced"] is False
    assert result["rework_status"] == "pending"
    assert result["task_type"] == "generate_architecture"
    assert result["attempt"] == 1
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"
    assert orch.get_gate_round(workflow.id, gate_id) == 1
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": gate_id,
        "decision": "rejected",
    }

    tasks = orch.list_tasks(workflow.id)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.id == result["task_id"]
    assert task.status == TaskStatus.PENDING
    assert task.metadata["task_type"] == "generate_architecture"
    assert task.metadata["rework_gate_id"] == gate_id
    assert task.metadata["rework_from_round"] == 1
    assert task.execution_parameters["current_state"] == PipelineState.ARCHITECTURE_GENERATING.value
    assert [queued.task_id for queued in queue.submitted] == [task.id]

    orch.advance_pipeline(workflow.id)
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"


def test_contracts_rework_uses_generate_contracts() -> None:
    orch, workflow = build_orchestrator(PipelineState.CONTRACTS_GENERATED)
    gate_id = "gate_contracts_approval"
    reject(orch, workflow, gate_id)

    result = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Regenerate contracts after schema review.",
    )

    assert result["task_type"] == "generate_contracts"
    task = orch.list_tasks(workflow.id)[0]
    assert task.execution_parameters["current_state"] == PipelineState.CONTRACTS_GENERATING.value
    assert workflow.current_state == PipelineState.CONTRACTS_GENERATED


@pytest.mark.parametrize(
    ("state", "gate_id"),
    [
        (PipelineState.REQUIREMENTS_VALIDATED, "gate_requirements_approval"),
        (PipelineState.DEPLOYED, "gate_release_approval"),
    ],
)
def test_rework_fails_closed_for_unsupported_gates(
    state: PipelineState,
    gate_id: str,
) -> None:
    orch, workflow = build_orchestrator(state)
    reject(orch, workflow, gate_id)

    with pytest.raises(ValueError, match="does not support automated rework"):
        orch.request_gate_rework(
            workflow.id,
            gate_id,
            actor="reviewer",
            reason="Try unsupported work.",
        )

    assert orch.list_tasks(workflow.id) == []
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"


def test_duplicate_rework_and_parallel_retry_are_blocked() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    first = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Regenerate architecture.",
    )

    with pytest.raises(ValueError, match=f"active rework task {first['task_id']}"):
        orch.request_gate_rework(
            workflow.id,
            gate_id,
            actor="reviewer",
            reason="Do it twice.",
        )

    with pytest.raises(ValueError, match=f"active rework task {first['task_id']}"):
        orch.retry_gate(
            workflow.id,
            gate_id,
            actor="reviewer",
            reason="Do not race the active rework.",
        )

    assert orch.get_gate_round(workflow.id, gate_id) == 1
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"


def test_successful_rework_completion_opens_next_pending_round_without_transition() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    request = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Regenerate architecture.",
    )
    task = orch.list_tasks(workflow.id)[0]
    task.result = {"architecture": {"revision": 2}}

    orch.handle_task_completion(task)

    assert task.status == TaskStatus.SUCCEEDED
    assert workflow.context["architecture"] == {"revision": 2}
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED
    assert orch.get_gate_round(workflow.id, gate_id) == 2
    assert orch.get_gate_decision(workflow.id, gate_id) is None
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": gate_id,
        "decision": "pending",
    }
    assert workflow.context["gate_decision_history"] == [
        {
            "gate_id": gate_id,
            "approver": "controller",
            "decision": "rejected",
            "round": 1,
        }
    ]
    assert workflow.context["gate_rework_history"] == [
        {
            "gate_id": gate_id,
            "actor": "reviewer",
            "reason": "Regenerate architecture.",
            "from_round": 1,
            "task_id": request["task_id"],
            "task_type": "generate_architecture",
            "attempt": 1,
            "status": "succeeded",
            "to_round": 2,
        }
    ]

    orch.advance_pipeline(workflow.id)
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED


def test_active_rework_survives_snapshot_restore() -> None:
    store = MemoryStore()
    orch, workflow = build_orchestrator(store=store)
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    request = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Durable rework.",
    )

    restored = PipelineOrchestrator(RuntimeStub(), state_store=store)
    status = restored.get_gate_rework_status(workflow.id, gate_id)

    assert status == {
        "supported": True,
        "active": True,
        "task_id": request["task_id"],
        "task_type": "generate_architecture",
        "round": 1,
    }
    assert restored.get_gate_decision(workflow.id, gate_id) == "rejected"
    assert restored.get_blocking_gate(workflow.id) == {
        "gate_id": gate_id,
        "decision": "rejected",
    }


def test_stale_rework_completion_never_changes_newer_gate_round() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    request = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Work that later becomes stale.",
    )
    task = orch.list_tasks(workflow.id)[0]

    # Simulate an externally restored/newer governance round before a late worker result.
    orch._set_gate_round(workflow, gate_id, 2)
    next(item for item in workflow.gates if item.id == gate_id).decision_id = None
    orch.handle_task_completion(task)

    assert orch.get_gate_round(workflow.id, gate_id) == 2
    assert orch.get_gate_decision(workflow.id, gate_id) is None
    record = workflow.context["gate_rework_history"][0]
    assert record["task_id"] == request["task_id"]
    assert record["status"] == "stale_completion"
    assert "to_round" not in record


def test_gate_list_exposes_backend_rework_authority(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    gates = execution_api.list_execution_gates(
        workflow.id,
        dor=object(),
        current_user=User(username="reviewer", organization_id="org-1"),
    )
    item = next(gate for gate in gates if gate["id"] == gate_id)
    assert item["retry_allowed"] is True
    assert item["rework_supported"] is True
    assert item["rework_allowed"] is True
    assert item["rework_active"] is False
    assert item["rework_task_id"] is None
    assert item["rework_task_type"] == "generate_architecture"

    request = orch.request_gate_rework(
        workflow.id,
        gate_id,
        actor="reviewer",
        reason="Queue governed rework.",
    )
    gates = execution_api.list_execution_gates(
        workflow.id,
        dor=object(),
        current_user=User(username="reviewer", organization_id="org-1"),
    )
    item = next(gate for gate in gates if gate["id"] == gate_id)
    assert item["retry_allowed"] is False
    assert item["rework_allowed"] is False
    assert item["rework_active"] is True
    assert item["rework_task_id"] == request["task_id"]


def test_rework_endpoint_queues_task_and_emits_event(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_architecture_approval"
    reject(orch, workflow, gate_id)
    events = []
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)
    monkeypatch.setattr(
        execution_api,
        "_emit",
        lambda _workflow, event_type, payload=None: events.append((event_type, payload)),
    )

    response = execution_api.rework_execution_gate(
        workflow.id,
        GateReworkRequest(gate_id=gate_id, reason="Regenerate architecture."),
        dor=object(),
        current_user=User(username="reviewer", organization_id="org-1"),
    )

    assert response["workflow_id"] == workflow.id
    assert response["gate_id"] == gate_id
    assert response["round"] == 1
    assert response["decision"] == "rejected"
    assert response["rework_status"] == "pending"
    assert response["status"] == PipelineState.ARCHITECTURE_GENERATED.value
    assert events == [
        (
            "GATE_REWORK_REQUESTED",
            {
                "gate_id": gate_id,
                "round": 1,
                "task_id": response["task_id"],
                "task_type": "generate_architecture",
                "actor": "reviewer",
            },
        )
    ]


def test_rework_endpoint_fails_closed_for_unsupported_gate(monkeypatch) -> None:
    orch, workflow = build_orchestrator(PipelineState.REQUIREMENTS_VALIDATED)
    gate_id = "gate_requirements_approval"
    reject(orch, workflow, gate_id)
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    with pytest.raises(HTTPException) as exc:
        execution_api.rework_execution_gate(
            workflow.id,
            GateReworkRequest(gate_id=gate_id, reason="No canonical upstream task."),
            dor=object(),
            current_user=User(username="reviewer", organization_id="org-1"),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == f"Gate {gate_id} does not support automated rework"
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"
