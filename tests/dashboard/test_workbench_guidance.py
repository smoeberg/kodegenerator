from types import SimpleNamespace

from dashboard.case_process_projection import AttentionState
from dashboard.workbench_guidance import (
    case_status_badge,
    gate_guidance,
    primary_action_text,
)


def _projection(*, state: AttentionState, owner: str, attention_required: bool = False, next_action=None):
    return SimpleNamespace(
        attention_state=state,
        owner_type=owner,
        attention_required=attention_required,
        next_action=next_action,
        attention_title="Afvent næste backend-skridt",
    )


def test_case_badge_prioritizes_human_attention_over_owner_copy() -> None:
    projection = _projection(
        state=AttentionState.NEEDS_DECISION,
        owner="human",
        attention_required=True,
    )
    assert case_status_badge(projection).label == "Kræver dig"


def test_case_badge_distinguishes_dor_external_and_completed() -> None:
    assert case_status_badge(_projection(state=AttentionState.DOR_WORKING, owner="dor")).label == "DOR arbejder"
    assert case_status_badge(_projection(state=AttentionState.WAITING_EXTERNAL, owner="external")).label == "Afventer andre"
    assert case_status_badge(_projection(state=AttentionState.COMPLETED, owner="none")).label == "Færdig"


def test_primary_action_text_uses_projection_and_never_invents_action() -> None:
    action = SimpleNamespace(label="Godkend løsningsforslaget")
    assert primary_action_text(_projection(state=AttentionState.NEEDS_DECISION, owner="human", next_action=action)) == "Godkend løsningsforslaget"
    assert primary_action_text(_projection(state=AttentionState.READY, owner="none")) == "Afvent næste backend-skridt"


def test_pending_gate_has_one_primary_and_one_secondary_human_choice() -> None:
    guidance = gate_guidance({"status": "human_required"})
    assert guidance.status_label == "Afventer din beslutning"
    assert guidance.primary_action == "Godkend"
    assert guidance.secondary_action == "Bed om ændringer"


def test_rejected_gate_prefers_backend_allowed_rework_and_keeps_retry_secondary() -> None:
    guidance = gate_guidance(
        {"status": "rejected", "can_rework": True, "can_retry": True}
    )
    assert guidance.primary_action == "Bed DOR om at rette"
    assert guidance.secondary_action == "Åbn for ny vurdering"


def test_rejected_gate_fails_closed_when_backend_exposes_no_recovery_action() -> None:
    guidance = gate_guidance(
        {"status": "rejected", "can_rework": False, "can_retry": False}
    )
    assert guidance.primary_action is None
    assert guidance.secondary_action is None
