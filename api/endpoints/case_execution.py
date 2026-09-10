"""Project-scoped execution boundary for canonical Sag flows.

This router does not create a second workflow engine. It validates the selected
Project + active plan through Core authority, then starts the existing pipeline
with an explicit project/plan binding so operator projections cannot guess
provenance.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, get_current_active_user, require_user_organization
from api.dependencies import get_dor
from domain.pipeline_states import PipelineState
from domain.principal import Principal
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from runtime.pipeline_registry import get_pipeline_registry
from runtime.project_runtime import ProjectNotFoundError
from services.event_bus import default_event_bus, project_topic

router = APIRouter(
    prefix="/api/v1/control-plane/projects",
    tags=["case-execution-v1"],
)


class StartProjectExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements_yaml: str = Field(min_length=1)
    plan_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def _context(dor: DORRuntime, current_user: User):
    organization_id = require_user_organization(current_user)
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"actor_id": current_user.username},
    )
    try:
        return dor.establish_context(
            principal=principal,
            organization_id=organization_id,
            actor_id=current_user.username,
        )
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc


def _project(dor: DORRuntime, current_user: User, project_id: str):
    context = _context(dor, current_user)
    try:
        return dor.projects.get_project(context, project_id)
    except CommandAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "authorization_denied",
                "reason_code": exc.decision.reason_code,
            },
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found"},
        ) from exc


def _require_active_scope(project: Any, plan_request_fingerprint: str) -> None:
    project_status = getattr(getattr(project, "status", None), "value", None)
    if project_status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "project_not_active"},
        )
    if getattr(project, "active_plan_request_fingerprint", None) != plan_request_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_project_scope"},
        )


def _scope(workflow: Any) -> tuple[str | None, str | None]:
    context = dict(getattr(workflow, "context", {}) or {})
    metadata = dict(getattr(workflow, "metadata", {}) or {})
    project_id = context.get("project_id") or metadata.get("project_id")
    plan_fingerprint = (
        context.get("plan_request_fingerprint")
        or metadata.get("plan_request_fingerprint")
    )
    return (
        str(project_id) if project_id else None,
        str(plan_fingerprint) if plan_fingerprint else None,
    )


def _find_scoped_workflow(orchestrator: Any, project_id: str, plan_fingerprint: str):
    orchestrator._restore()
    candidates = []
    for workflow in orchestrator._workflows.values():
        bound_project, bound_plan = _scope(workflow)
        if bound_project == project_id and bound_plan == plan_fingerprint:
            candidates.append(workflow)
    if not candidates:
        return None
    candidates.sort(
        key=lambda workflow: getattr(workflow, "updated_at", None),
        reverse=True,
    )
    return candidates[0]


def _snapshot(orchestrator: Any, workflow: Any, *, replayed: bool = False) -> dict[str, Any]:
    payload = dict(orchestrator.get_pipeline_status(workflow.id))
    project_id, plan_fingerprint = _scope(workflow)
    payload.update(
        {
            "project_id": project_id,
            "plan_request_fingerprint": plan_fingerprint,
            "replayed": replayed,
        }
    )
    return payload


@router.get("/{project_id}/execution")
def get_project_execution(
    project_id: str,
    plan_request_fingerprint: str = Query(pattern=r"^[0-9a-f]{64}$"),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    """Return only the execution bound to the selected Project + active plan."""
    project = _project(dor, current_user, project_id)
    _require_active_scope(project, plan_request_fingerprint)
    organization_id = require_user_organization(current_user)
    orchestrator = get_pipeline_registry(
        dor,
        organization_id=organization_id,
    ).orchestrator
    workflow = _find_scoped_workflow(
        orchestrator,
        project_id,
        plan_request_fingerprint,
    )
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_execution_not_found"},
        )
    return _snapshot(orchestrator, workflow)


@router.post("/{project_id}/execution", status_code=status.HTTP_202_ACCEPTED)
def start_project_execution(
    project_id: str,
    request: StartProjectExecutionRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    """Start the existing pipeline after exact active-scope revalidation."""
    project = _project(dor, current_user, project_id)
    _require_active_scope(project, request.plan_request_fingerprint)
    organization_id = require_user_organization(current_user)
    orchestrator = get_pipeline_registry(
        dor,
        organization_id=organization_id,
    ).orchestrator

    existing = _find_scoped_workflow(
        orchestrator,
        project_id,
        request.plan_request_fingerprint,
    )
    if existing is not None:
        return _snapshot(orchestrator, existing, replayed=True)

    try:
        workflow = orchestrator._adapter.create_pipeline_from_yaml(
            yaml_content=request.requirements_yaml,
            organization_id=organization_id,
            created_by=current_user.username,
            project_id=project_id,
            plan_request_fingerprint=request.plan_request_fingerprint,
        )
        orchestrator._workflows[workflow.id] = workflow
        orchestrator._transition(
            workflow,
            PipelineState.REQUIREMENTS_VALIDATED,
            {"requirements_complete": True},
        )
        orchestrator._persist()
        orchestrator.advance_pipeline(workflow.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    snapshot = _snapshot(orchestrator, workflow)
    default_event_bus.publish(
        project_topic(project_id),
        "EXECUTION_STARTED",
        {
            "workflow_id": workflow.id,
            "project_id": project_id,
            "plan_request_fingerprint": request.plan_request_fingerprint,
            "state": snapshot.get("current_state"),
        },
    )
    return snapshot
