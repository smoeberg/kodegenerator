"""Contract tests for the project-scoped Sag execution boundary."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.endpoints.case_execution import (
    _find_scoped_workflow,
    _require_active_scope,
    _scope,
)


def _project(*, status: str = "active", plan: str = "a" * 64):
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        active_plan_request_fingerprint=plan,
    )


def _workflow(
    workflow_id: str,
    *,
    project_id: str = "project-a",
    plan: str = "a" * 64,
    updated_at: datetime | None = None,
):
    return SimpleNamespace(
        id=workflow_id,
        context={"project_id": project_id, "plan_request_fingerprint": plan},
        metadata={},
        updated_at=updated_at or datetime(2026, 9, 10, tzinfo=timezone.utc),
    )


def test_active_scope_requires_active_project_and_exact_plan() -> None:
    plan = "a" * 64
    _require_active_scope(_project(plan=plan), plan)

    with pytest.raises(HTTPException) as inactive:
        _require_active_scope(_project(status="created", plan=plan), plan)
    assert inactive.value.status_code == 409
    assert inactive.value.detail == {"error": "project_not_active"}

    with pytest.raises(HTTPException) as stale:
        _require_active_scope(_project(plan=plan), "b" * 64)
    assert stale.value.status_code == 409
    assert stale.value.detail == {"error": "stale_project_scope"}


def test_workflow_scope_uses_only_explicit_project_and_plan_binding() -> None:
    workflow = _workflow("wf-1")
    assert _scope(workflow) == ("project-a", "a" * 64)

    unbound = SimpleNamespace(
        id="wf-legacy",
        context={"project_name": "project-a"},
        metadata={},
        updated_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    assert _scope(unbound) == (None, None)


def test_exact_scope_lookup_does_not_guess_and_prefers_newest_match() -> None:
    older = _workflow(
        "wf-old",
        updated_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
    )
    newer = _workflow(
        "wf-new",
        updated_at=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
    )
    other_plan = _workflow(
        "wf-other",
        plan="b" * 64,
        updated_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )

    class Orchestrator:
        _workflows = {
            older.id: older,
            newer.id: newer,
            other_plan.id: other_plan,
        }

        def _restore(self):
            return None

    orchestrator = Orchestrator()
    selected = _find_scoped_workflow(orchestrator, "project-a", "a" * 64)
    assert selected is newer
    assert _find_scoped_workflow(orchestrator, "project-a", "c" * 64) is None
