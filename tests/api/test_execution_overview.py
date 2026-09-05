from __future__ import annotations

from types import SimpleNamespace

from api.auth import User
import api.endpoints.execution_overview as overview_module
from api.endpoints.execution_overview import _execution_summary, list_executions, router


class FakeOrchestrator:
    def __init__(self, workflows, snapshots, blockers=None, reworks=None) -> None:
        self._workflows = {workflow.id: workflow for workflow in workflows}
        self.snapshots = snapshots
        self.blockers = blockers or {}
        self.reworks = reworks or {}
        self.restore_calls = 0

    def _restore(self) -> None:
        self.restore_calls += 1

    def get_pipeline_status(self, workflow_id: str):
        return self.snapshots[workflow_id]

    def get_blocking_gate(self, workflow_id: str):
        return self.blockers.get(workflow_id)

    def get_gate_rework_status(self, workflow_id: str, gate_id: str):
        return self.reworks[(workflow_id, gate_id)]


def _workflow(workflow_id: str, organization_id: str):
    return SimpleNamespace(
        id=workflow_id,
        context={"organization_id": organization_id},
        metadata={},
    )


def _snapshot(workflow_id: str, *, state: str = "implementation", updated: str = "2026-09-05T10:00:00+00:00"):
    return {
        "workflow_id": workflow_id,
        "project_name": f"Project {workflow_id}",
        "current_state": state,
        "created_at": "2026-09-05T09:00:00+00:00",
        "updated_at": updated,
        "tasks": [
            {"id": f"task-{workflow_id}", "task_type": "implementation", "status": "running"}
        ],
    }


def test_execution_overview_router_exposes_tenant_scoped_list_route() -> None:
    routes = {(route.path, frozenset(getattr(route, "methods", ()) or ())) for route in router.routes}
    assert ("/api/v1/execution", frozenset({"GET"})) in routes


def test_execution_summary_surfaces_human_decision_and_rework_state() -> None:
    workflow = _workflow("wf-1", "org-1")
    orch = FakeOrchestrator(
        [workflow],
        {"wf-1": _snapshot("wf-1")},
        blockers={"wf-1": {"gate_id": "gate-1", "decision": "rejected"}},
        reworks={
            ("wf-1", "gate-1"): {
                "active": True,
                "task_id": "task-rework-1",
                "task_type": "generate_architecture",
            }
        },
    )

    summary = _execution_summary(orch, workflow)

    assert summary["blocking_gate"] == {"gate_id": "gate-1", "decision": "rejected"}
    assert summary["rework"] == {
        "active": True,
        "task_id": "task-rework-1",
        "task_type": "generate_architecture",
    }
    assert summary["action_required"] == "rework_active"
    assert summary["terminal"] is False


def test_list_executions_filters_cross_tenant_and_sorts_latest_first(monkeypatch) -> None:
    own_old = _workflow("wf-old", "org-1")
    own_new = _workflow("wf-new", "org-1")
    other = _workflow("wf-other", "org-2")
    orch = FakeOrchestrator(
        [own_old, own_new, other],
        {
            "wf-old": _snapshot("wf-old", updated="2026-09-05T10:00:00+00:00"),
            "wf-new": _snapshot("wf-new", updated="2026-09-05T11:00:00+00:00"),
            "wf-other": _snapshot("wf-other", updated="2026-09-05T12:00:00+00:00"),
        },
    )
    monkeypatch.setattr(overview_module, "_orchestrator", lambda _dor: orch)

    result = list_executions(
        dor=SimpleNamespace(),
        current_user=User(username="alice", organization_id="org-1"),
    )

    assert [item["workflow_id"] for item in result] == ["wf-new", "wf-old"]
    assert all("wf-other" != item["workflow_id"] for item in result)
    assert orch.restore_calls == 1


def test_list_executions_fails_closed_without_organization(monkeypatch) -> None:
    monkeypatch.setattr(
        overview_module,
        "_orchestrator",
        lambda _dor: (_ for _ in ()).throw(AssertionError("must not load registry")),
    )

    result = list_executions(
        dor=SimpleNamespace(),
        current_user=User(username="alice", organization_id=None),
    )

    assert result == []
