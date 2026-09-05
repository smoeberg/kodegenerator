"""Read-only operator overview projection for canonical execution pipelines."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import get_pipeline_registry

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])

_TERMINAL_STATES = {"released", "failed", "cancelled"}
_COMPLETED_TASK_STATES = {"succeeded", "success", "completed", "done"}


def _orchestrator(dor: DORRuntime) -> PipelineOrchestrator:
    return get_pipeline_registry(dor).orchestrator


def _workflow_organization_id(workflow: Any) -> str | None:
    context = dict(getattr(workflow, "context", {}) or {})
    metadata = dict(getattr(workflow, "metadata", {}) or {})
    value = context.get("organization_id") or metadata.get("organization_id")
    return str(value) if value else None


def _execution_summary(
    orchestrator: PipelineOrchestrator,
    workflow: Any,
) -> dict[str, Any]:
    """Project one workflow into the minimal operator-facing execution contract."""
    snapshot = orchestrator.get_pipeline_status(workflow.id)
    tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
    task_open = sum(
        1
        for task in tasks
        if isinstance(task, dict)
        and str(task.get("status") or "").strip().lower()
        not in _COMPLETED_TASK_STATES
    )

    current_state = str(snapshot.get("current_state") or "unknown")
    terminal = current_state.strip().lower() in _TERMINAL_STATES
    blocker = orchestrator.get_blocking_gate(workflow.id)
    blocking_gate: dict[str, Any] | None = None
    rework: dict[str, Any] | None = None
    action_required = "terminal" if terminal else "none"

    if blocker is not None:
        gate_id = str(blocker.get("gate_id") or "")
        decision = str(blocker.get("decision") or "pending")
        blocking_gate = {"gate_id": gate_id, "decision": decision}
        if decision == "pending":
            action_required = "human_decision"
        elif decision == "rejected":
            rework_status = orchestrator.get_gate_rework_status(workflow.id, gate_id)
            rework = {
                "active": bool(rework_status.get("active")),
                "task_id": rework_status.get("task_id"),
                "task_type": rework_status.get("task_type"),
            }
            action_required = "rework_active" if rework["active"] else "rejected"
    elif not terminal and task_open:
        action_required = "work_in_progress"

    return {
        "workflow_id": str(snapshot.get("workflow_id") or workflow.id),
        "project_name": str(snapshot.get("project_name") or "—"),
        "current_state": current_state,
        "created_at": str(snapshot.get("created_at") or ""),
        "updated_at": str(snapshot.get("updated_at") or ""),
        "task_total": len(tasks),
        "task_open": task_open,
        "terminal": terminal,
        "blocking_gate": blocking_gate,
        "rework": rework,
        "action_required": action_required,
    }


@router.get("")
def list_executions(
    dor: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List canonical pipeline summaries owned by the authenticated organization."""
    organization_id = current_user.organization_id
    if not organization_id:
        return []

    orchestrator = _orchestrator(dor)
    # API and workers can be separate processes; refresh the durable snapshot so
    # the overview is based on the same persisted pipeline authority as workers.
    orchestrator._restore()

    summaries = [
        _execution_summary(orchestrator, workflow)
        for workflow in orchestrator._workflows.values()
        if _workflow_organization_id(workflow) == organization_id
    ]
    summaries.sort(key=lambda item: item["updated_at"], reverse=True)
    return summaries
