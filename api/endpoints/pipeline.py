# api/endpoints/pipeline.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional

from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from api.dependencies import get_runtime, get_current_user
from api.schemas.pipeline import (
    StartPipelineRequest,
    PipelineStatusResponse,
    PipelineListResponse,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

@router.post("/start", response_model=PipelineStatusResponse)
async def start_pipeline(
    request: StartPipelineRequest,
    runtime: DORRuntime = Depends(get_runtime),
    user = Depends(get_current_user),
) -> PipelineStatusResponse:
    """
    Start a new software factory pipeline.
    """
    try:
        orchestrator = PipelineOrchestrator(runtime)
        workflow_id = await orchestrator.start_pipeline(
            requirements_yaml=request.requirements_yaml,
            organization_id=user.organization_id,
            created_by=user.id,
        )
        
        # Start the pipeline
        await orchestrator.advance_pipeline(workflow_id)
        
        status = await orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**status)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start pipeline: {str(e)}"
        )

@router.get("/{workflow_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_runtime),
    user = Depends(get_current_user),
) -> PipelineStatusResponse:
    """
    Get the status of a pipeline.
    """
    try:
        orchestrator = PipelineOrchestrator(runtime)
        status = await orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**status)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.post("/{workflow_id}/advance")
async def advance_pipeline(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_runtime),
    user = Depends(get_current_user),
) -> dict:
    """
    Manually advance a pipeline to the next state.
    Useful after a gate is approved.
    """
    try:
        orchestrator = PipelineOrchestrator(runtime)
        await orchestrator.advance_pipeline(workflow_id)
        return {"status": "ok", "message": "Pipeline advanced"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/", response_model=PipelineListResponse)
async def list_pipelines(
    runtime: DORRuntime = Depends(get_runtime),
    user = Depends(get_current_user),
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PipelineListResponse:
    """
    List all pipelines for the organization.
    """
    workflows = await runtime.list_workflows(
        organization_id=user.organization_id,
        state=state,
        limit=limit,
        offset=offset,
    )
    
    return PipelineListResponse(
        items=[
            {
                "workflow_id": w.id,
                "name": w.name,
                "current_state": w.current_state.value,
                "project_name": w.context.get("project_name"),
                "created_at": w.created_at.isoformat(),
                "updated_at": w.updated_at.isoformat(),
            }
            for w in workflows
        ],
        total=await runtime.count_workflows(
            organization_id=user.organization_id,
            state=state,
        ),
        limit=limit,
        offset=offset,
    )
