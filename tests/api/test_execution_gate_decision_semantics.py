"""Regression tests for fail-closed execution gate decisions and retries."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import execution as execution_api
from api.endpoints.execution import GateDecisionRequest, GateRetryRequest
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
            "round": 1,
        }
    ]
    assert "gate_approvals" not in workflow.context
    assert orch.get_gate_round(workflow.id, "gate_requirements_approval") == 1
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
    assert workflow.context["gate_approvals"][-1] == {
        "gate_id": "gate_requirements_approval",
        "approver": "alice",
        "decision": "approved",
        "round": 1,
    }
    assert orch.get_blocking_gate(workflow.id) is None


def test_gate_decision_is_single_assignment_within_round() -> None:
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


def test_retry_opens_new_pending_round_without_advancing() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="alice",
        decision="rejected",
    )

    result = orch.retry_gate(
        workflow.id,
        gate_id,
        actor="bob",
        reason="Requirements were corrected and need a fresh human decision.",
    )

    assert result == {
        "gate_id": gate_id,
        "round": 2,
        "decision": None,
        "blocking": True,
        "workflow_advanced": False,
    }
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED
    assert gate(workflow, gate_id).decision_id is None
    assert orch.get_gate_round(workflow.id, gate_id) == 2
    assert orch.get_gate_decision(workflow.id, gate_id) is None
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": gate_id,
        "decision": "pending",
    }
    assert workflow.context["gate_decision_history"] == [
        {
            "gate_id": gate_id,
            "approver": "alice",
            "decision": "rejected",
            "round": 1,
        }
    ]
    assert workflow.context["gate_retry_history"] == [
        {
            "gate_id": gate_id,
            "actor": "bob",
            "reason": "Requirements were corrected and need a fresh human decision.",
            "from_round": 1,
            "to_round": 2,
        }
    ]

    orch.advance_pipeline(workflow.id)
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED


def test_retry_is_rejected_while_new_round_is_pending() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="alice",
        decision="rejected",
    )
    orch.retry_gate(workflow.id, gate_id, actor="bob", reason="Re-evaluate")

    with pytest.raises(ValueError, match="cannot be retried from decision pending"):
        orch.retry_gate(workflow.id, gate_id, actor="carol", reason="Again")


def test_retry_requires_nonblank_reason() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="alice",
        decision="rejected",
    )

    with pytest.raises(ValueError, match="retry reason is required"):
        orch.retry_gate(workflow.id, gate_id, actor="bob", reason="   ")


def test_second_round_can_be_approved_without_erasing_first_rejection() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="alice",
        decision="rejected",
    )
    orch.retry_gate(workflow.id, gate_id, actor="bob", reason="Corrected")

    result = orch.decide_gate(
        workflow.id,
        gate_id,
        approver="carol",
        decision="approved",
    )

    assert result["approved"] is True
    assert result["workflow_advanced"] is True
    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATING
    assert workflow.context["gate_decision_history"] == [
        {
            "gate_id": gate_id,
            "approver": "alice",
            "decision": "rejected",
            "round": 1,
        },
        {
            "gate_id": gate_id,
            "approver": "carol",
            "decision": "approved",
            "round": 2,
        },
    ]
    assert orch.get_gate_round(workflow.id, gate_id) == 2
    assert orch.get_gate_decision(workflow.id, gate_id) == "approved"


def test_retry_round_survives_snapshot_restore() -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(
        workflow.id,
        gate_id,
        approver="alice",
        decision="rejected",
    )
    orch.retry_gate(workflow.id, gate_id, actor="bob", reason="Corrected")

    restored = PipelineOrchestrator(RuntimeStub(), state_store=orch._state_store)

    assert restored.get_gate_round(workflow.id, gate_id) == 2
    assert restored.get_gate_decision(workflow.id, gate_id) is None
    assert restored.get_blocking_gate(workflow.id) == {
        "gate_id": gate_id,
        "decision": "pending",
    }
    restored_workflow = restored._get_workflow(workflow.id)
    assert restored_workflow is not None
    assert restored_workflow.context["gate_retry_history"][-1]["to_round"] == 2


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
    assert orch.get_gate_round(workflow.id, legacy_gate.id) == 1
    assert orch.get_blocking_gate(workflow.id) == {
        "gate_id": legacy_gate.id,
        "decision": "rejected",
    }


def test_legacy_decision_id_without_audit_record_stays_approved_in_round_one() -> None:
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


def test_manual_advance_returns_409_when_retried_gate_is_pending(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(workflow.id, gate_id, approver="alice", decision="rejected")
    orch.retry_gate(workflow.id, gate_id, actor="bob", reason="Corrected")
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    with pytest.raises(HTTPException) as exc:
        execution_api.advance_execution(
            workflow.id,
            dor=object(),
            current_user=User(username="alice", organization_id="org-1"),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "workflow_blocked_by_gate:gate_requirements_approval:pending"
    )
    assert workflow.current_state == PipelineState.REQUIREMENTS_VALIDATED


def test_gate_list_exposes_round_and_retry_authority(monkeypatch) -> None:
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
    assert requirements_gate["round"] == 1
    assert requirements_gate["retry_allowed"] is True


def test_retry_endpoint_opens_round_and_emits_event(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(workflow.id, gate_id, approver="alice", decision="rejected")
    events = []
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)
    monkeypatch.setattr(
        execution_api,
        "_emit",
        lambda _workflow, event_type, payload=None: events.append(
            (event_type, payload)
        ),
    )

    response = execution_api.retry_execution_gate(
        workflow.id,
        GateRetryRequest(gate_id=gate_id, reason="Corrected requirements"),
        dor=object(),
        current_user=User(username="bob", organization_id="org-1"),
    )

    assert response == {
        "workflow_id": workflow.id,
        "gate_id": gate_id,
        "round": 2,
        "decision": None,
        "blocking": True,
        "workflow_advanced": False,
        "status": PipelineState.REQUIREMENTS_VALIDATED.value,
    }
    assert events == [
        (
            "GATE_RETRY_OPENED",
            {"gate_id": gate_id, "round": 2, "actor": "bob"},
        )
    ]


def test_retry_endpoint_fails_closed_for_blank_reason(monkeypatch) -> None:
    orch, workflow = build_orchestrator()
    gate_id = "gate_requirements_approval"
    orch.decide_gate(workflow.id, gate_id, approver="alice", decision="rejected")
    monkeypatch.setattr(execution_api, "_orchestrator", lambda _dor: orch)

    with pytest.raises(HTTPException) as exc:
        execution_api.retry_execution_gate(
            workflow.id,
            GateRetryRequest(gate_id=gate_id, reason="   "),
            dor=object(),
            current_user=User(username="bob", organization_id="org-1"),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "retry reason is required"
    assert orch.get_gate_decision(workflow.id, gate_id) == "rejected"


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
