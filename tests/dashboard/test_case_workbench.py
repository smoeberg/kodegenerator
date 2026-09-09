"""Tests for the shared Sag / Mit arbejde / Overblik workbench adapter."""
from dashboard.case_process_projection import AttentionState
from dashboard.case_workbench import (
    build_case_workbench,
    find_case,
    overview_counts,
)


def _project(project_id: str, *, name: str, status: str = "active", actions=None):
    payload = {
        "project_id": project_id,
        "name": name,
        "status": status,
    }
    if actions is not None:
        payload["allowed_actions"] = actions
    return payload


def _execution(
    workflow_id: str,
    project_id: str | None,
    *,
    state: str,
    action_required: str = "none",
    updated_at: str = "2026-09-09T10:00:00Z",
    blocking_gate=None,
    rework=None,
    actions=None,
):
    payload = {
        "workflow_id": workflow_id,
        "project_id": project_id,
        "current_state": state,
        "action_required": action_required,
        "updated_at": updated_at,
        "blocking_gate": blocking_gate,
        "rework": rework,
    }
    if actions is not None:
        payload["allowed_actions"] = actions
    return payload


def test_builds_one_case_per_backend_project():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha"), _project("p2", name="Beta")],
        [],
    )
    assert [item.projection.case_id for item in snapshot.cases] == ["p1", "p2"]


def test_links_execution_only_by_explicit_project_id():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha")],
        [_execution("w1", "p1", state="code_generating", action_required="work_in_progress")],
    )
    item = snapshot.cases[0]
    assert item.execution["workflow_id"] == "w1"
    assert item.projection.owner_type == "dor"


def test_does_not_guess_link_from_project_name():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha")],
        [
            {
                "workflow_id": "w1",
                "project_name": "Alpha",
                "current_state": "code_generating",
                "action_required": "work_in_progress",
            }
        ],
    )
    assert snapshot.cases[0].execution is None
    assert [item["workflow_id"] for item in snapshot.unlinked_executions] == ["w1"]


def test_unknown_project_relation_stays_unlinked():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha")],
        [_execution("w1", "missing-project", state="code_generating")],
    )
    assert snapshot.cases[0].execution is None
    assert len(snapshot.unlinked_executions) == 1


def test_uses_newest_linked_execution_for_case_projection():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha")],
        [
            _execution(
                "old",
                "p1",
                state="requirements_draft",
                updated_at="2026-09-08T10:00:00Z",
            ),
            _execution(
                "new",
                "p1",
                state="tests_running",
                action_required="work_in_progress",
                updated_at="2026-09-09T10:00:00Z",
            ),
        ],
    )
    item = snapshot.cases[0]
    assert item.execution["workflow_id"] == "new"
    assert item.linked_execution_count == 2
    assert item.projection.human_status == "DOR kontrollerer løsningen"


def test_cases_requiring_action_come_from_projection_attention():
    snapshot = build_case_workbench(
        [_project("p1", name="Decision"), _project("p2", name="Working")],
        [
            _execution(
                "w1",
                "p1",
                state="requirements_validated",
                action_required="human_decision",
                blocking_gate={"gate_id": "gate_requirements_approval"},
                actions=["approve", "reject"],
            ),
            _execution(
                "w2",
                "p2",
                state="code_generating",
                action_required="work_in_progress",
            ),
        ],
    )
    assert [item.projection.case_id for item in snapshot.requiring_action] == ["p1"]
    assert snapshot.requiring_action[0].projection.next_action.label == "Godkend kravene"


def test_rework_active_is_waiting_for_dor_not_human_work():
    snapshot = build_case_workbench(
        [_project("p1", name="Rework")],
        [
            _execution(
                "w1",
                "p1",
                state="architecture_generating",
                action_required="rework_active",
                rework={"active": True},
            )
        ],
    )
    assert snapshot.requiring_action == ()
    assert len(snapshot.waiting_for_dor) == 1
    assert snapshot.waiting_for_dor[0].projection.attention_state is AttentionState.REWORK_IN_PROGRESS


def test_completed_cases_are_grouped_consistently():
    snapshot = build_case_workbench(
        [_project("p1", name="Done", status="completed")],
        [_execution("w1", "p1", state="released", action_required="terminal")],
    )
    assert len(snapshot.completed) == 1
    assert snapshot.completed[0].projection.attention_state is AttentionState.COMPLETED


def test_overview_counts_are_derived_from_same_snapshot():
    snapshot = build_case_workbench(
        [
            _project("p1", name="Decision"),
            _project("p2", name="Working"),
            _project("p3", name="Done", status="completed"),
        ],
        [
            _execution(
                "w1",
                "p1",
                state="requirements_validated",
                action_required="human_decision",
                blocking_gate={"gate_id": "gate_requirements_approval"},
                actions=["approve"],
            ),
            _execution(
                "w2",
                "p2",
                state="code_generating",
                action_required="work_in_progress",
            ),
            _execution("w3", "p3", state="released", action_required="terminal"),
            _execution("legacy", None, state="tests_running"),
        ],
    )
    assert overview_counts(snapshot) == {
        "cases": 3,
        "requires_action": 1,
        "waiting_for_dor": 1,
        "waiting_external": 0,
        "completed": 1,
        "unlinked_executions": 1,
    }


def test_attention_cases_sort_before_background_work():
    snapshot = build_case_workbench(
        [_project("p1", name="Zeta"), _project("p2", name="Alpha")],
        [
            _execution(
                "w1",
                "p1",
                state="architecture_generated",
                action_required="human_decision",
                blocking_gate={"gate_id": "gate_architecture_approval"},
                actions=["approve"],
            ),
            _execution(
                "w2",
                "p2",
                state="code_generating",
                action_required="work_in_progress",
            ),
        ],
    )
    assert [item.projection.case_id for item in snapshot.cases] == ["p1", "p2"]


def test_find_case_uses_canonical_case_identity():
    snapshot = build_case_workbench(
        [_project("p1", name="Alpha"), _project("p2", name="Beta")],
        [],
    )
    assert find_case(snapshot, "p2").projection.title == "Beta"
    assert find_case(snapshot, "missing") is None
    assert find_case(snapshot, None) is None


def test_project_without_identity_is_not_exposed_as_case():
    snapshot = build_case_workbench([{"name": "Broken backend row"}], [])
    assert snapshot.cases == ()
