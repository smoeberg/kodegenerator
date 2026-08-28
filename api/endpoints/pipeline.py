# api/endpoints/pipeline.py

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.schemas.pipeline import (
    StartPipelineRequest,
    PipelineStatusResponse,
    PipelineListResponse,
)
from domain.principal import Principal
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _create_pipeline_orchestrator(runtime: DORRuntime) -> PipelineOrchestrator:
    return PipelineOrchestrator(runtime)


@router.post("/start", response_model=PipelineStatusResponse)
def start_pipeline(
    request: StartPipelineRequest,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
) -> PipelineStatusResponse:
    """Start a new software factory pipeline from requirements YAML."""
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
        workflow_id = orchestrator.start_pipeline(
            requirements_yaml=request.requirements_yaml,
            organization_id=organization_id,
            created_by=current_user.username,
        )
        orchestrator.advance_pipeline(workflow_id)
        status = orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start pipeline: {str(exc)}",
        ) from exc


@router.get("/{workflow_id}", response_model=PipelineStatusResponse)
def get_pipeline_status(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> PipelineStatusResponse:
    """Get the status of a pipeline."""
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
        return PipelineStatusResponse(**orchestrator.get_pipeline_status(workflow_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{workflow_id}/advance")
def advance_pipeline(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Manually advance a pipeline to the next state (useful after gate approval)."""
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
        orchestrator.advance_pipeline(workflow_id)
        return {"status": "ok", "message": "Pipeline advanced"}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/", response_model=PipelineListResponse)
def list_pipelines(
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PipelineListResponse:
    """List all pipelines for the organization."""
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"username": current_user.username},
    )
    context = runtime.establish_context(
        principal=principal,
        organization_id=organization_id,
        actor_id=current_user.username,
    )
    workflows = [
        w for w in runtime.list_workflows(context)
        if (state is None or w.current_state.value == state)
    ][offset:offset + limit]

    return PipelineListResponse(
        items=[
            {
                "workflow_id": w.id,
                "name": w.name,
                "current_state": w.current_state.value,
                "project_name": (w.context or {}).get("project_name"),
                "created_at": w.created_at.isoformat(),
                "updated_at": w.updated_at.isoformat(),
            }
            for w in workflows
        ],
        total=len(workflows),
        limit=limit,
        offset=offset,
    )
