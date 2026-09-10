import pytest

from dashboard.case_process_projection import (
    AttentionState,
    GATE_COPY,
    PIPELINE_STATE_TO_PHASE,
    ProcessPhase,
    project_case,
)


CANONICAL_PIPELINE_STATES = tuple(PIPELINE_STATE_TO_PHASE)
PROJECT_STATES = (
    "created",
    "launch_requested",
    "active",
    "completion_pending",
    "completed",
    "cancelled",
    "archived",
)


@pytest.mark.parametrize("state", CANONICAL_PIPELINE_STATES)
def test_every_canonical_pipeline_state_projects(state):
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {"workflow_id": "wf-1", "current_state": state, "action_required": "none"},
    )
    assert projection.phase is PIPELINE_STATE_TO_PHASE[state]
    assert projection.human_status
    assert len(projection.process_steps) == 6


@pytest.mark.parametrize("status", PROJECT_STATES)
def test_every_project_state_projects(status):
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": status},
    )
    assert projection.title == "Demo"
    assert projection.phase is ProcessPhase.CLARIFICATION


def test_created_case_is_actionable_but_nba_fails_closed_without_backend_action():
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "created"},
    )
    assert projection.attention_state is AttentionState.READY
    assert projection.attention_required is True
    assert projection.owner_type == "human"
    assert projection.next_action is None


def test_nba_selects_backend_allowed_project_action_only():
    projection = project_case(
        "case-1",
        {
            "project_id": "project-1",
            "name": "Demo",
            "status": "created",
            "allowed_actions": ["launch"],
        },
    )
    assert projection.next_action is not None
    assert projection.next_action.id == "launch"
    assert projection.next_action.id in projection.allowed_actions


def test_nba_never_invents_project_action():
    projection = project_case(
        "case-1",
        {
            "project_id": "project-1",
            "name": "Demo",
            "status": "created",
            "allowed_actions": ["cancel"],
        },
    )
    assert projection.next_action is None


@pytest.mark.parametrize(
    "gate_id,state,expected_label",
    [
        ("gate_requirements_approval", "requirements_validated", "Godkend kravene"),
        ("gate_architecture_approval", "architecture_generated", "Godkend løsningsforslaget"),
        ("gate_contracts_approval", "contracts_generated", "Godkend grundlaget"),
        ("gate_release_approval", "deployed", "Godkend leveringen"),
    ],
)
def test_gate_specific_copy_and_nba(gate_id, state, expected_label):
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "current_state": state,
            "action_required": "human_decision",
            "blocking_gate": {"gate_id": gate_id, "decision": "pending"},
            "allowed_actions": ["approve", "reject"],
        },
    )
    assert projection.attention_state is AttentionState.NEEDS_DECISION
    assert projection.next_action is not None
    assert projection.next_action.id == "approve"
    assert projection.next_action.id in projection.allowed_actions
    assert projection.next_action.label == expected_label
    assert projection.attention_title == GATE_COPY[gate_id]["title"]


def test_rejected_prefers_rework_only_when_backend_allows_it():
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "current_state": "tests_failed",
            "action_required": "rejected",
            "blocking_gate": {"gate_id": "gate_release_approval", "decision": "rejected"},
            "allowed_actions": ["rework", "retry"],
        },
    )
    assert projection.attention_state is AttentionState.BLOCKED
    assert projection.next_action is not None
    assert projection.next_action.id == "rework"
    assert projection.blockers[0]["id"] == "gate_release_approval"


def test_rejected_without_backend_recovery_action_has_no_nba():
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "current_state": "tests_failed",
            "action_required": "rejected",
            "blocking_gate": {"gate_id": "gate_release_approval", "decision": "rejected"},
            "allowed_actions": [],
        },
    )
    assert projection.next_action is None


def test_rework_is_owned_by_dor_and_has_no_nba():
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "current_state": "code_generating",
            "action_required": "rework_active",
            "rework": {"active": True},
            "allowed_actions": ["advance"],
        },
    )
    assert projection.attention_state is AttentionState.REWORK_IN_PROGRESS
    assert projection.owner_type == "dor"
    assert projection.next_action is None


def test_failed_state_is_explicit_and_does_not_invent_action():
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "current_state": "failed",
            "action_required": "terminal",
            "error": "timeout",
        },
    )
    assert projection.attention_state is AttentionState.FAILED
    assert projection.attention_required is True
    assert projection.next_action is None


@pytest.mark.parametrize(
    "project_status,execution_state,expected",
    [
        ("completed", "released", AttentionState.COMPLETED),
        ("cancelled", "cancelled", AttentionState.CANCELLED),
        ("archived", "released", AttentionState.ARCHIVED),
    ],
)
def test_terminal_project_states(project_status, execution_state, expected):
    projection = project_case(
        "case-1",
        {"project_id": "project-1", "name": "Demo", "status": project_status},
        {"workflow_id": "wf-1", "current_state": execution_state, "action_required": "terminal"},
    )
    assert projection.attention_state is expected
    assert projection.owner_type == "none"
    assert projection.next_action is None


@pytest.mark.parametrize(
    "execution",
    [
        {"workflow_id": "wf-1", "action_required": "none"},
        {"workflow_id": "wf-1", "current_state": "future_state", "action_required": "none"},
    ],
)
def test_unknown_or_missing_execution_state_fails_closed(execution):
    projection = project_case(
        "case-1",
        {
            "project_id": "project-1",
            "name": "Demo",
            "status": "active",
            "allowed_actions": ["advance"],
        },
        {**execution, "allowed_actions": ["advance"]},
    )
    assert projection.phase is ProcessPhase.UNKNOWN
    assert projection.human_status == "Status kan ikke fastslås"
    assert projection.attention_state is AttentionState.UNKNOWN
    assert projection.attention_title == "Status kan ikke fastslås"
    assert projection.owner_type == "none"
    assert projection.attention_required is False
    assert projection.allowed_actions == ()
    assert projection.next_action is None
    assert projection.process_steps == []
    assert projection.evidence_completed == []
    assert projection.evidence_missing == []
