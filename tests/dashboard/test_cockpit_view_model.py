import pytest

from dashboard.cockpit_view_model import (
    build_evidence_trace,
    build_execution_summary,
    gate_decision_payload,
    interpret_advance_error,
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


def test_normalize_gates_preserves_pending_approved_and_rejected_states():
    gates = normalize_gates(
        [
            {
                "id": "security_gate",
                "name": "Security",
                "description": "Review security evidence",
                "resolved": False,
                "decision": None,
                "blocking": True,
            },
            {
                "id": "approved_gate",
                "name": "Approved",
                "description": "Approved evidence",
                "resolved": True,
                "decision": "approved",
                "blocking": False,
            },
            {
                "id": "rejected_gate",
                "name": "Rejected",
                "description": "Rejected evidence",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
            },
        ]
    )

    assert gates[0]["status"] == "human_required"
    assert gates[0]["can_decide"] is True
    assert gates[0]["blocking"] is True

    assert gates[1]["status"] == "approved"
    assert gates[1]["decision"] == "approved"
    assert gates[1]["can_decide"] is False

    assert gates[2]["status"] == "rejected"
    assert gates[2]["decision"] == "rejected"
    assert gates[2]["blocking"] is True
    assert gates[2]["can_decide"] is False


def test_normalize_gates_keeps_legacy_resolved_gate_locked():
    gate = normalize_gates(
        [
            {
                "id": "legacy_gate",
                "name": "Legacy",
                "description": "No decision field",
                "resolved": True,
            }
        ]
    )[0]

    assert gate["status"] == "resolved"
    assert gate["decision"] is None
    assert gate["can_decide"] is False


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


def test_interpret_advance_error_treats_blocking_gate_as_governance_state():
    error = interpret_advance_error(
        409,
        "workflow_blocked_by_gate:gate_architecture_approval:rejected",
    )

    assert error["kind"] == "gate_blocked"
    assert error["gate_id"] == "gate_architecture_approval"
    assert error["decision"] == "rejected"
    assert "blokeret" in error["message"]


def test_interpret_advance_error_keeps_generic_api_errors_generic():
    error = interpret_advance_error(500, "backend unavailable")

    assert error == {
        "kind": "api_error",
        "gate_id": None,
        "decision": None,
        "message": "backend unavailable",
    }


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


def test_evidence_trace_uses_canonical_payloads_without_inventing_direct_links():
    trace = build_evidence_trace(
        {
            "workflow_id": "wf-trace-1",
            "current_state": "TESTS_PASSED",
            "tasks": [
                {
                    "id": "task-code",
                    "task_type": "generate_code",
                    "status": "SUCCEEDED",
                },
                {
                    "id": "task-tests",
                    "task_type": "run_tests",
                    "status": "SUCCEEDED",
                },
            ],
            "context": {
                "requirements": {
                    "requirements": [
                        {
                            "id": "REQ-1",
                            "description": "Expose governed endpoint",
                            "acceptance_criteria": ["Returns 200", "Tenant scoped"],
                        }
                    ]
                },
                "tests_generated": True,
                "tests_passed": True,
                "gate_decision_history": [
                    {
                        "gate_id": "gate_requirements_approval",
                        "approver": "alice",
                        "decision": "approved",
                    }
                ],
            },
        },
        [
            {
                "id": "gate_requirements_approval",
                "name": "Requirements Approval",
                "description": "Human approves requirements",
                "resolved": True,
                "decision": "approved",
                "blocking": False,
            }
        ],
        [
            {
                "id": "proposal-1",
                "title": "Implement endpoint",
                "summary": "Adds endpoint",
                "status": "proposed",
                "created_by": "agent",
                "created_at": "2026-09-04T10:00:00Z",
                "files": [{"path": "api/example.py", "diff": "+route"}],
            }
        ],
    )

    assert trace["workflow_id"] == "wf-trace-1"
    assert trace["requirements"] == [
        {
            "id": "REQ-1",
            "description": "Expose governed endpoint",
            "acceptance_criteria": ["Returns 200", "Tenant scoped"],
            "linkage": "workflow_scope",
        }
    ]
    assert trace["tasks"][0]["linkage"] == "workflow_scope"
    assert trace["agent_work"][0]["task_id"] == "task-code"
    assert trace["agent_work"][0]["evidence_level"] == "task_execution_only"
    assert trace["proposals"][0]["file_count"] == 1
    assert trace["tests"]["tests_generated"] is True
    assert trace["tests"]["tests_passed"] is True
    assert trace["tests"]["tasks"][0]["id"] == "task-tests"
    assert trace["decisions"] == [
        {
            "gate_id": "gate_requirements_approval",
            "decision": "approved",
            "approver": "alice",
            "linkage": "gate_id",
            "source": "gate_decision_history",
        }
    ]
    assert trace["linkage"]["requirement_to_task"] == "workflow_scope"
    assert trace["linkage"]["gate_to_decision"] == "gate_id"
    assert "requirement_id -> task_id" in trace["gaps"][0]


def test_evidence_trace_falls_back_to_gate_state_for_legacy_decision():
    trace = build_evidence_trace(
        {"workflow_id": "wf-legacy", "context": {}, "tasks": []},
        [
            {
                "id": "gate-release",
                "name": "Release",
                "resolved": True,
                "decision": "rejected",
                "blocking": True,
            }
        ],
        [],
    )

    assert trace["decisions"] == [
        {
            "gate_id": "gate-release",
            "decision": "rejected",
            "approver": "—",
            "linkage": "gate_id",
            "source": "gate_state",
        }
    ]
    assert trace["gates"][0]["blocking"] is True


def test_evidence_trace_is_stable_for_missing_or_malformed_payloads():
    trace = build_evidence_trace(None, {"not": "a list"}, "bad proposals")

    assert trace["workflow_id"] == "—"
    assert trace["requirements"] == []
    assert trace["tasks"] == []
    assert trace["proposals"] == []
    assert trace["gates"] == []
    assert trace["decisions"] == []
    assert all(stage["count"] == 0 for stage in trace["stages"])
