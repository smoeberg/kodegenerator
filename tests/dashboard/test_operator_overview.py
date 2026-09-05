from dashboard.operator_overview import normalize_execution_overview, overview_metrics


def test_operator_overview_prioritizes_human_attention_over_running_work() -> None:
    payload = [
        {
            "workflow_id": "wf-running",
            "project_name": "Running",
            "current_state": "implementation",
            "updated_at": "2026-09-05T12:00:00+00:00",
            "task_total": 2,
            "task_open": 1,
            "terminal": False,
            "blocking_gate": None,
            "rework": None,
            "action_required": "work_in_progress",
        },
        {
            "workflow_id": "wf-human",
            "project_name": "Needs approval",
            "current_state": "architecture_review",
            "updated_at": "2026-09-05T11:00:00+00:00",
            "task_total": 1,
            "task_open": 0,
            "terminal": False,
            "blocking_gate": {"gate_id": "gate-1", "decision": "pending"},
            "rework": None,
            "action_required": "human_decision",
        },
    ]

    rows = normalize_execution_overview(payload)

    assert [row["workflow_id"] for row in rows] == ["wf-human", "wf-running"]
    assert rows[0]["action_label"] == "Kræver human beslutning"


def test_operator_overview_metrics_are_backend_state_derived() -> None:
    rows = normalize_execution_overview(
        [
            {
                "workflow_id": "wf-human",
                "terminal": False,
                "blocking_gate": {"gate_id": "gate-1", "decision": "pending"},
                "action_required": "human_decision",
            },
            {
                "workflow_id": "wf-rejected",
                "terminal": False,
                "blocking_gate": {"gate_id": "gate-2", "decision": "rejected"},
                "action_required": "rejected",
            },
            {
                "workflow_id": "wf-rework",
                "terminal": False,
                "blocking_gate": {"gate_id": "gate-3", "decision": "rejected"},
                "rework": {"active": True, "task_id": "task-r", "task_type": "generate_architecture"},
                "action_required": "rework_active",
            },
            {
                "workflow_id": "wf-done",
                "terminal": True,
                "blocking_gate": None,
                "action_required": "terminal",
            },
        ]
    )

    assert overview_metrics(rows) == {
        "active": 3,
        "requires_action": 2,
        "blocking": 3,
        "rework": 1,
    }


def test_operator_overview_ignores_malformed_records_and_unknown_actions() -> None:
    rows = normalize_execution_overview(
        [
            None,
            {"project_name": "missing id"},
            {"workflow_id": "wf-1", "action_required": "made_up", "task_total": "bad"},
        ]
    )

    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "wf-1"
    assert rows[0]["action_required"] == "none"
    assert rows[0]["task_total"] == 0
