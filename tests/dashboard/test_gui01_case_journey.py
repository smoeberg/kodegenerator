from datetime import datetime, timezone
from pathlib import Path

import pytest

from dashboard.case_process_projection import AttentionState, ProcessPhase, project_case
from dashboard.case_proposal_provenance import resolve_proposal_provenance
from dashboard.copenhagen_greeting import copenhagen_greeting, greeting_for_hour
from dashboard.workbench_guidance import case_status_badge


VIEWS = Path("dashboard/case_shell_views.py")
IMPLEMENTATION = Path("dashboard/case_implementation.py")


@pytest.mark.parametrize(
    "hour,expected",
    [
        (5, "Godmorgen"),
        (11, "Godmorgen"),
        (12, "God eftermiddag"),
        (17, "God eftermiddag"),
        (18, "Godaften"),
        (23, "Godaften"),
        (0, "Godaften"),
    ],
)
def test_copenhagen_greeting_boundaries(hour, expected):
    assert greeting_for_hour(hour) == expected


def test_copenhagen_greeting_converts_timestamp_to_local_timezone():
    # 10:00 UTC is 12:00 CEST on 10 September 2026.
    now = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    assert copenhagen_greeting(now) == "God eftermiddag"


def test_unknown_execution_state_never_projects_ready_or_actionable():
    projection = project_case(
        "case-1",
        {"project_id": "case-1", "name": "Demo", "status": "active"},
        {
            "workflow_id": "wf-1",
            "project_id": "case-1",
            "current_state": "not_in_runtime_contract",
            "allowed_actions": ["advance"],
        },
    )
    assert projection.phase is ProcessPhase.UNKNOWN
    assert projection.attention_state is AttentionState.UNKNOWN
    assert projection.human_status == "Status kan ikke fastslås"
    assert projection.next_action is None
    assert case_status_badge(projection).label == "Status ukendt"


def test_missing_execution_provenance_fails_closed():
    result = {
        "project_id": "case-1",
        "plan_id": "plan-1",
        "plan_request_fingerprint": "a" * 64,
        "response": {
            "execution_id": "proposal-run-1",
            "proposal": {"proposal_id": "proposal-1"},
        },
    }
    assert (
        resolve_proposal_provenance(
            case_id="case-1",
            execution={
                "workflow_id": "wf-1",
                "project_id": "case-1",
                # Missing exact plan_request_fingerprint: no relation may be invented.
            },
            proposal_result=result,
        )
        is None
    )


def test_valid_case_plan_execution_proposal_projection_uses_exact_backend_ids():
    result = {
        "project_id": "case-1",
        "plan_id": "plan-1",
        "plan_request_fingerprint": "b" * 64,
        "response": {
            "execution_id": "proposal-run-7",
            "proposal": {"proposal_id": "proposal-9"},
        },
    }
    provenance = resolve_proposal_provenance(
        case_id="case-1",
        execution={
            "workflow_id": "workflow-3",
            "project_id": "case-1",
            "plan_request_fingerprint": "b" * 64,
        },
        proposal_result=result,
    )
    assert provenance is not None
    assert provenance.case_id == "case-1"
    assert provenance.plan_id == "plan-1"
    assert provenance.execution_id == "workflow-3"
    assert provenance.proposal_id == "proposal-9"
    assert provenance.proposal_execution_id == "proposal-run-7"


def test_canonical_journey_order_is_visible_and_decision_is_last():
    source = VIEWS.read_text(encoding="utf-8")
    expected = (
        '"Sag"',
        '"Plan"',
        '"Aktivt arbejdsgrundlag"',
        '"Execution"',
        '"Proposal"',
        '"Beslutning"',
    )
    positions = [source.index(value, source.index("CANONICAL_CASE_JOURNEY")) for value in expected]
    assert positions == sorted(positions)
    assert '<div class="section-label">AFKLARING</div>' not in source


def test_authority_paths_remain_backend_owned_and_patch_apply_is_absent():
    source = IMPLEMENTATION.read_text(encoding="utf-8")
    assert 'f"/api/v1/control-plane/projects/{project_id}/execution"' in source
    assert 'client.post("/implementation-agent/proposals"' in source
    assert "/api/v1/execution/start" not in source
    assert 'client.post("/implementation-agent/executions"' not in source
    assert "Patch Apply er en separat capability" in source
