# api/endpoints/pipeline.py

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.schemas.pipeline import (
    PipelineListResponse,
    PipelineStatusResponse,
    StartPipelineRequest,
)
from domain.principal import Principal
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import get_pipeline_registry

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _pipeline_context(runtime: DORRuntime, current_user: User, organization_id: str):
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"username": current_user.username},
    )
    try:
        return runtime.establish_context(
            principal=principal,
            organization_id=organization_id,
            actor_id=current_user.username,
        )
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


def _create_pipeline_orchestrator(
    runtime: DORRuntime, organization_id: str
) -> PipelineOrchestrator:
    return get_pipeline_registry(runtime, organization_id=organization_id).orchestrator


def _workflow_for_organization(
    orchestrator: PipelineOrchestrator,
    workflow_id: str,
    organization_id: str,
):
    workflow = orchestrator._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline not found",
        )
    metadata = dict(workflow.metadata or {})
    context = dict(workflow.context or {})
    workflow_organization_id = (
        metadata.get("organization_id")
        or context.get("organization_id")
        or getattr(workflow, "organization_id", None)
    )
    if workflow_organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline not found",
        )
    return workflow


@router.post("/start", response_model=PipelineStatusResponse)
def start_pipeline(
    request: StartPipelineRequest,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
) -> PipelineStatusResponse:
    """Start a new software factory pipeline from requirements YAML."""
    _pipeline_context(runtime, current_user, organization_id)
    try:
        orchestrator = _create_pipeline_orchestrator(runtime, organization_id)
        workflow_id = orchestrator.start_pipeline(
            requirements_yaml=request.requirements_yaml,
            organization_id=organization_id,
            created_by=current_user.username,
        )
        orchestrator.advance_pipeline(workflow_id)
        pipeline_status = orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**pipeline_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start pipeline",
        ) from exc


@router.get("/{workflow_id}", response_model=PipelineStatusResponse)
def get_pipeline_status(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
) -> PipelineStatusResponse:
    """Get the status of a pipeline in the authenticated organization."""
    _pipeline_context(runtime, current_user, organization_id)
    orchestrator = _create_pipeline_orchestrator(runtime, organization_id)
    _workflow_for_organization(orchestrator, workflow_id, organization_id)
    try:
        return PipelineStatusResponse(**orchestrator.get_pipeline_status(workflow_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
        ) from exc


@router.post("/{workflow_id}/advance")
def advance_pipeline(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
) -> dict:
    """Advance a pipeline only inside the authenticated organization boundary."""
    _pipeline_context(runtime, current_user, organization_id)
    orchestrator = _create_pipeline_orchestrator(runtime, organization_id)
    _workflow_for_organization(orchestrator, workflow_id, organization_id)
    try:
        orchestrator.advance_pipeline(workflow_id)
        return {"status": "ok", "message": "Pipeline advanced"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/", response_model=PipelineListResponse)
def list_pipelines(
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PipelineListResponse:
    """List all canonical workflows for the authenticated organization."""
    context = _pipeline_context(runtime, current_user, organization_id)
    workflows = [
        workflow
        for workflow in runtime.list_workflows(context)
        if state is None or workflow.current_state.value == state
    ]
    total = len(workflows)
    workflows = workflows[offset : offset + limit]

    return PipelineListResponse(
        items=[
            {
                "workflow_id": workflow.id,
                "name": workflow.name,
                "current_state": workflow.current_state.value,
                "project_name": (workflow.context or {}).get("project_name"),
                "created_at": workflow.created_at.isoformat(),
                "updated_at": workflow.updated_at.isoformat(),
            }
            for workflow in workflows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
