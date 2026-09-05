from __future__ import annotations

from dashboard.cockpit_lifecycle import build_cockpit_lifecycle


def _execution(*, state: str = "implementation", tasks: list[dict] | None = None, error=None):
    payload = {
        "workflow_id": "wf-1",
        "project_name": "Demo",
        "current_state": state,
        "tasks": tasks if tasks is not None else [],
    }
    if error is not None:
        payload["error"] = error
    return payload


def _human_gate() -> dict:
    return {
        "id": "gate-human",
        "name": "Human approval",
        "resolved": False,
        "decision": None,
        "blocking": True,
        "round": 1,
    }


def _rework_gate() -> dict:
    return {
        "id": "gate-rework",
        "name": "Architecture approval",
        "resolved": True,
        "decision": "rejected",
        "blocking": True,
        "round": 1,
        "rework_active": True,
        "rework_task_id": "task-rework-1",
        "rework_task_type": "generate_architecture",
        "retry_allowed": False,
        "rework_allowed": False,
    }


def test_human_decision_is_primary_operator_focus() -> None:
    lifecycle = build_cockpit_lifecycle(
        _execution(),
        [_human_gate()],
        [{"id": "proposal-1", "title": "Proposal"}],
    )

    assert lifecycle["attention"]["kind"] == "warning"
    assert lifecycle["attention"]["title"] == "Human decision kræves"
    assert "gate-human" in lifecycle["attention"]["detail"]
    assert lifecycle["gate_value"] == "1 human · 1 blocking"
    assert lifecycle["proposal_value"] == "1"


def test_active_rework_takes_precedence_over_rejected_blocker() -> None:
    lifecycle = build_cockpit_lifecycle(_execution(), [_rework_gate()], [])

    assert lifecycle["attention"]["kind"] == "info"
    assert lifecycle["attention"]["title"] == "Governed rework kører"
    assert "task-rework-1" in lifecycle["attention"]["detail"]
    assert "fail-closed" in lifecycle["attention"]["focus"]


def test_execution_error_has_highest_attention_priority() -> None:
    lifecycle = build_cockpit_lifecycle(
        _execution(error="worker_failed"),
        [_human_gate()],
        [],
    )

    assert lifecycle["attention"]["kind"] == "error"
    assert lifecycle["attention"]["title"] == "Execution kræver fejlsøgning"
    assert lifecycle["attention"]["detail"] == "worker_failed"


def test_unavailable_gate_snapshot_never_claims_ready_state() -> None:
    lifecycle = build_cockpit_lifecycle(
        _execution(),
        [],
        [],
        gates_available=False,
    )

    assert lifecycle["gate_value"] == "utilgængelig"
    assert lifecycle["evidence_value"] == "delvist"
    assert lifecycle["attention"]["kind"] == "warning"
    assert lifecycle["attention"]["title"] == "Gate-status er utilgængelig"
    assert "Undlad at antage" in lifecycle["attention"]["focus"]


def test_open_tasks_are_presented_as_work_in_progress() -> None:
    lifecycle = build_cockpit_lifecycle(
        _execution(
            tasks=[
                {"id": "done", "status": "completed"},
                {"id": "open", "status": "running"},
            ]
        ),
        [],
        [],
    )

    assert lifecycle["task_value"] == "1 / 2"
    assert lifecycle["attention"]["kind"] == "info"
    assert lifecycle["attention"]["title"] == "Arbejde er stadig aktivt"


def test_clean_snapshot_does_not_claim_backend_advance_authority() -> None:
    lifecycle = build_cockpit_lifecycle(
        _execution(tasks=[{"id": "done", "status": "completed"}]),
        [],
        [],
    )

    assert lifecycle["attention"]["kind"] == "success"
    assert lifecycle["attention"]["title"] == "Ingen kendt lokal blocker i snapshot"
    assert lifecycle["attention"]["focus"] == "Backend afgør fortsat, om Advance accepteres."


def test_terminal_execution_points_operator_to_evidence() -> None:
    lifecycle = build_cockpit_lifecycle(_execution(state="released"), [], [])

    assert lifecycle["attention"]["kind"] == "success"
    assert lifecycle["attention"]["title"] == "Execution er afsluttet"
    assert "Evidence Trace" in lifecycle["attention"]["focus"]
