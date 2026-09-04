"""Regression tests for fail-closed execution gate decisions."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import execution as execution_api
from api.endpoints.execution import GateDecisionRequest
from domain.pipeline_gates import get_pipeline_gates
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
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


def build_orchestrator() -> tuple[PipelineOrchestrator, Workflow]:
    store = MemoryStore()
    orch = PipelineOrchestrator(RuntimeStub(), state_store=store)
    now = datetime.now(timezone.utc)
    workflow = Workflow(
        id="wf-gate-001",
        name="Gate semantics",
        current_state=PipelineState.REQUIREMENTS_VALIDATED,
        states=list(PipelineState),
        transitions=get_pipeline_transitions(),
        gates=get_pipeline_gates(),
        context={"organization_id": "org-1"},
        metadata={"organization_id": "org-1"},
        created_at=now,
        updated_at=now,
    )
    orch._workflows[workflow.id] = workflow
    return orch, workflow


def gate(workflow: Workflow, gate_id: str):
    return next(item for item in workflow.gates if item.id == gate_id)


def test_rejected_gate_is_recorded_but_does_not_advance() -> None:
    orch, workflow = build_orchestrator()

    result = orch.decide_gate(
        workflow.id,
        "gate_requirements_approval",
        approver="alice",
        decision="rejected",
    )

    assert result == {
        "decision": "rejected",
        "approved": False,
        "workflow_advanced": False,
    }
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED
    assert gate(workflow, "gate_requirements_approval").decision_id is not None
    assert workflow.context["gate_decision_history"] == [
        {
            "gate_id": "gate_requirements_approval",
            "approver": "alice",
            "decision": "rejected",
        }
    ]
    assert "gate_approvals" not in workflow.context
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": "gate_requirements_approval",
        "decision": "rejected",
    }

    orch.advance_pipeline(workflow.id)
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED


def test_approved_gate_advances_pipeline_and_records_approval() -> None:
    orch, workflow = build_orchestrator()

    result = orch.decide_gate(
        workflow.id,
        "gate_requirements_approval",
        approver="alice",
        decision="approved",
    )

    assert result["decision"] == "approved"
    assert result["approved"] is True
    assert result["workflow_advanced"] is True
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATING
    assert orch.get_gate_decision(workflow.id, "gate_requirements_approval") == "approved"
    assert workflow.context["gate_approvals"][-1]["decision"] == "approved"
    assert orch.get_blocking_gate(workflow.id) is None


def test_gate_decision_is_single_assignment() -> None:
    orch, workflow = build_orchestrator()
    orch.decide_gate(
        workflow.id,
        "gate_requirements_approval",
        approver="alice",
        decision="rejected",
    )

    with pytest.raises(ValueError, match="already decided .*rejected"):
        orch.decide_gate(
            workflow.id,
            "gate_requirements_approval",
            approver="bob",
            decision="approved",
        )


def test_legacy_rejected_gate_remains_blocking_after_upgrade() -> None:
    orch, workflow = build_orchestrator()
    legacy_gate = gate(workflow, "gate_requirements_approval")
    legacy_gate.decision_id = "decision-legacy"
    workflow.context["gate_approvals"] = [
        {
            "gate_id": legacy_gate.id,
            "approver": "legacy-user",
            "decision": "rejected",
        }
    ]

    assert orch.get_gate_decision(workflow.id, legacy_gate.id) == "rejected"
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": legacy_gate.id,
        "decision": "rejected",
    }


def test_legacy_decision_id_without_audit_record_stays_approved() -> None:
    orch, workflow = build_orchestrator()
    legacy_gate = gate(workflow, "gate_requirements_approval")
    legacy_gate.decision_id = "decision-legacy"

    assert orch.get_gate_decision(workflow.id, legacy_gate.id) == "approved"
    assert orch.get_blocking_gate(workflow.id) is None


def test_manual_advance_returns_409_when_rejected_gate_blocks(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    orch.decide_gate(
        workflow.id,
        "gate_requirements_approval",
        approver="alice",
        decision="rejected",
    )
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    with pytest.raises(HTTPException) as exc:
        execution_api.advance_execution(
            workflow.id,
            dor=object(),
            current_user=User(username="alice", organization_id="org-1"),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "workflow_blocked_by_gate:gate_requirements_approval:rejected"
    )
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED


def test_gate_list_exposes_decision_and_blocking_state(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    orch.decide_gate(
        workflow.id,
        "gate_requirements_approval",
        approver="alice",
        decision="rejected",
    )
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    gates = execution_api.list_execution_gates(
        workflow.id,
        dor=object(),
        current_user=User(username="alice", organization_id="org-1"),
    )

    requirements_gate = next(
        item for item in gates if item["id"] == "gate_requirements_approval"
    )
    assert requirements_gate["resolved"] is True
    assert requirements_gate["decision"] == "rejected"
    assert requirements_gate["blocking"] is True


def test_decide_endpoint_emits_rejection_without_claiming_advance(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    events = []
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)
    monkeypatch.setattr(
        execution_api,
        "_emit",
        lambda _workflow, event_type, payload=None: events.append(
            (event_type, payload)
        ),
    )

    response = execution_api.decide_execution_gate(
        workflow.id,
        GateDecisionRequest(
            gate_id="gate_requirements_approval",
            decision="rejected",
        ),
        dor=object(),
        current_user=User(username="alice", organization_id="org-1"),
    )

    assert response["decision"] == "rejected"
    assert response["approved"] is False
    assert response["workflow_advanced"] is False
    assert response["status"] == PipelineState.REQUIREMENTS_VALIDATED.value
    assert events == [
        (
            "GATE_DECISION",
            {
                "gate_id": "gate_requirements_approval",
                "decision": "rejected",
                "approved": False,
                "workflow_advanced": False,
                "actor": "alice",
            },
        )
    ]
