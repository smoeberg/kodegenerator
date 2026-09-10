from customer_gui.view_model import (
    CANONICAL_JOURNEY,
    UNKNOWN_STATUS,
    JourneyState,
    completion_evidence,
    customer_execution_status,
    decision_actions,
    journey,
    resolve_provenance,
)


FP = "a" * 64


def project(**updates):
    value = {
        "project_id": "case-1",
        "status": "active",
        "active_plan_request_fingerprint": FP,
    }
    value.update(updates)
    return value


def execution(**updates):
    value = {
        "workflow_id": "wf-1",
        "project_id": "case-1",
        "plan_request_fingerprint": FP,
        "current_state": "code_generating",
    }
    value.update(updates)
    return value


def test_unknown_and_missing_execution_state_fail_closed() -> None:
    for payload in ({}, {"current_state": "brand_new_state"}, None):
        status = customer_execution_status(payload)
        assert status.label == UNKNOWN_STATUS
        assert status.state is JourneyState.UNKNOWN


def test_known_execution_states_use_explicit_mapping() -> None:
    assert customer_execution_status({"current_state": "requirements_draft"}).label == "Planlægger"
    assert customer_execution_status({"current_state": "tests_running"}).label == "Kontrollerer resultat"
    assert customer_execution_status({"current_state": "tests_failed"}).state is JourneyState.FAILED
    assert customer_execution_status({"current_state": "released"}).label == "Leveret"


def test_exact_provenance_chain_is_accepted() -> None:
    proposal = {"id": "proposal-1", "workflow_id": "wf-1"}
    value = resolve_provenance(project(), execution(), proposal)
    assert value is not None
    assert value.case_id == "case-1"
    assert value.plan_request_fingerprint == FP
    assert value.workflow_id == "wf-1"
    assert value.proposal_id == "proposal-1"


def test_missing_or_mismatched_provenance_fails_closed() -> None:
    assert resolve_provenance(project(), None) is None
    assert resolve_provenance(project(), execution(project_id="other")) is None
    assert resolve_provenance(project(), execution(plan_request_fingerprint="b" * 64)) is None
    assert resolve_provenance(project(), execution(), {"id": "p", "workflow_id": "other"}) is None


def test_decision_actions_only_follow_backend_gate_state() -> None:
    assert decision_actions({"id": "g", "blocking": True, "resolved": False, "decision": None}) == ("approve", "reject")
    assert decision_actions({"id": "g", "blocking": True, "resolved": True, "decision": "rejected", "rework_allowed": True}) == ("request_changes",)
    assert decision_actions({"id": "g", "blocking": False, "resolved": False, "decision": None}) == ()
    assert decision_actions({"id": "g", "blocking": True, "resolved": True, "decision": "rejected", "rework_allowed": False}) == ()


def test_customer_journey_order_is_canonical() -> None:
    gates = [{"id": "g", "blocking": True, "resolved": False, "decision": None}]
    proposals = [{"id": "proposal-1", "workflow_id": "wf-1"}]
    steps = journey(project(), execution(), gates, proposals)
    assert tuple(step.label for step in steps) == CANONICAL_JOURNEY
    assert steps[-1].state is JourneyState.CURRENT


def test_verified_completion_evidence_requires_backend_completion_record() -> None:
    assert completion_evidence(project(status="completed", completion_record_id=None)) == ()
    evidence = completion_evidence(
        project(
            status="completed",
            completion_record_id="record-1",
            completed_by="alice",
            completed_at="2026-09-10T10:00:00Z",
        )
    )
    assert evidence[0]["record_id"] == "record-1"


def test_unrelated_proposal_makes_proposal_step_unknown_not_ready() -> None:
    steps = journey(project(), execution(), (), [{"id": "p", "workflow_id": "other"}])
    assert steps[4].state is JourneyState.UNKNOWN
