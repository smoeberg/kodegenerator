# api/endpoints/pipeline.py

from fastapi import APIRouter, Depends, HTTPException, status as fastapi_status
from typing import Optional

from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import get_pipeline_orchestrator
from api.dependencies import get_dor
from api.auth import get_current_user
from api.schemas.pipeline import (
    StartPipelineRequest,
    PipelineStatusResponse,
    PipelineListResponse,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/start", response_model=PipelineStatusResponse)
async def start_pipeline(
    request: StartPipelineRequest,
    runtime: DORRuntime = Depends(get_dor),
    user=Depends(get_current_user),
) -> PipelineStatusResponse:
    """
    Start a new software factory pipeline.
    """
    try:
        orchestrator = get_pipeline_orchestrator()
        workflow_id = await orchestrator.start_pipeline(
            requirements_yaml=request.requirements_yaml,
            organization_id=getattr(user, "organization_id", "default-org"),
            created_by=getattr(user, "id", "admin"),
        )

        # Move through any automatic (non-gate) steps, e.g. to REQUIREMENTS_VALIDATED
        await orchestrator.advance_pipeline(workflow_id)

        status = await orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**status)
    except ValueError as e:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start pipeline: {str(e)}",
        )


@router.post("/{workflow_id}/decide", response_model=dict)
async def decide_gate(
    workflow_id: str,
    body: dict,
    runtime: DORRuntime = Depends(get_dor),
    user=Depends(get_current_user),
) -> dict:
    """
    Record a human gate decision.
    Payload: {"gate_id": "gate_requirements_approval", "decision": "approved"}
    """
    gate_id = body.get("gate_id")
    decision = body.get("decision")
    if not gate_id or not decision:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail="Both 'gate_id' and 'decision' are required",
        )
    try:
        orchestrator = get_pipeline_orchestrator()
        return await orchestrator.decide_gate(workflow_id, gate_id, decision)
    except ValueError as e:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/{workflow_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    user=Depends(get_current_user),
) -> PipelineStatusResponse:
    """
    Get the status of a pipeline.
    """
    try:
        orchestrator = get_pipeline_orchestrator()
        status = await orchestrator.get_pipeline_status(workflow_id)
        return PipelineStatusResponse(**status)
    except ValueError as e:
        raise HTTPException(
            status_code=fastapi_status.HTTP_404_NOT_FOUND, detail=str(e)
        )


@router.post("/{workflow_id}/advance", response_model=dict)
async def advance_pipeline(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    user=Depends(get_current_user),
) -> dict:
    """
    Manually advance a pipeline to the next state.
    Useful after a gate is approved.
    """
    try:
        orchestrator = get_pipeline_orchestrator()
        return await orchestrator.advance_pipeline(workflow_id)
    except ValueError as e:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/", response_model=PipelineListResponse)
async def list_pipelines(
    runtime: DORRuntime = Depends(get_dor),
    user=Depends(get_current_user),
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PipelineListResponse:
    """
    List all pipelines for the organization.
    """
    pipelines = get_pipeline_orchestrator().list_pipelines(state=state)
    items = [
        {
            "workflow_id": p["workflow_id"],
            "name": p.get("project_name", ""),
            "current_state": p["current_state"],
            "project_name": p.get("project_name"),
            "created_at": p.get("created_at", ""),
            "updated_at": p.get("updated_at", ""),
        }
        for p in pipelines
    ]
    return PipelineListResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )
