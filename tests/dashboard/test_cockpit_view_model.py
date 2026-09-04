import pytest

from dashboard.cockpit_view_model import (
    build_execution_summary,
    gate_decision_payload,
    normalize_gates,
    normalize_proposals,
)


def test_execution_summary_counts_completed_and_open_tasks():
    summary = build_execution_summary(
        {
            "workflow_id": "wf-1",
            "project_name": "demo",
            "current_state": "CODE_GENERATING",
            "tasks": [
                {"id": "task-1", "status": "SUCCEEDED"},
                {"id": "task-2", "status": "PENDING"},
            ],
            "error": None,
        }
    )

    assert summary["workflow_id"] == "wf-1"
    assert summary["current_state"] == "CODE_GENERATING"
    assert summary["task_total"] == 2
    assert summary["task_completed"] == 1
    assert summary["task_open"] == 1
    assert "aktive tasks" in summary["next_action"]


def test_execution_summary_prioritizes_error_guidance():
    summary = build_execution_summary(
        {
            "workflow_id": "wf-2",
            "current_state": "TESTS_RUNNING",
            "tasks": [],
            "error": "tests failed",
        }
    )

    assert summary["error"] == "tests failed"
    assert "execution-fejlen" in summary["next_action"]


def test_normalize_gates_marks_only_unresolved_gates_as_human_required():
    gates = normalize_gates(
        [
            {
                "id": "security_gate",
                "name": "Security",
                "description": "Review security evidence",
                "resolved": False,
            },
            {
                "id": "test_gate",
                "name": "Tests",
                "description": "Review tests",
                "resolved": True,
            },
        ]
    )

    assert gates[0]["status"] == "human_required"
    assert gates[1]["status"] == "resolved"


def test_gate_decision_payload_matches_fastapi_contract():
    assert gate_decision_payload("security_gate", "approved") == {
        "gate_id": "security_gate",
        "decision": "approved",
    }
    assert gate_decision_payload("security_gate", "rejected") == {
        "gate_id": "security_gate",
        "decision": "rejected",
    }


@pytest.mark.parametrize("decision", ["approve", "reject", "", "investigate"])
def test_gate_decision_payload_rejects_non_contract_values(decision):
    with pytest.raises(ValueError):
        gate_decision_payload("security_gate", decision)


def test_normalize_proposals_prefers_patch_or_diff_for_inspection():
    proposals = normalize_proposals(
        [
            {
                "id": "proposal-1",
                "title": "Add endpoint",
                "summary": "Adds a governed endpoint",
                "status": "proposed",
                "created_by": "agent",
                "created_at": "2026-09-04T10:00:00Z",
                "files": [
                    {"path": "api/example.py", "patch": "@@ -1 +1 @@"},
                    {"filename": "tests/test_example.py", "diff": "+assert True"},
                ],
            }
        ]
    )

    assert proposals[0]["files"][0]["display_name"] == "api/example.py"
    assert proposals[0]["files"][0]["diff"] == "@@ -1 +1 @@"
    assert proposals[0]["files"][1]["display_name"] == "tests/test_example.py"
    assert proposals[0]["files"][1]["diff"] == "+assert True"
