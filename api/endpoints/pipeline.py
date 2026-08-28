# api/endpoints/pipeline.py

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.schemas.pipeline import (
    PipelineListResponse,
    PipelineStatusResponse,
    PipelineWorkerClaimRequest,
    PipelineWorkerCompleteRequest,
    StartPipelineRequest,
)
from domain.principal import Principal
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import get_pipeline_registry

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _create_pipeline_orchestrator(runtime: DORRuntime) -> PipelineOrchestrator:
    return get_pipeline_registry(runtime).orchestrator


def _require_pipeline_access(
    orchestrator: PipelineOrchestrator,
    workflow_id: str,
    current_user: User,
    organization_id: str,
):
    """Resolve one workflow without leaking another tenant's pipeline."""
    workflow = orchestrator._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
        )
    metadata = dict(workflow.metadata or {})
    if metadata.get("organization_id") != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
        )
    if metadata.get("created_by") != current_user.username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Pipeline access denied"
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
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
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
    organization_id: str = Query(...),
) -> PipelineStatusResponse:
    """Get the status of a pipeline."""
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
        _require_pipeline_access(
            orchestrator, workflow_id, current_user, organization_id
        )
        return PipelineStatusResponse(**orchestrator.get_pipeline_status(workflow_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{workflow_id}/advance")
def advance_pipeline(
    workflow_id: str,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
    organization_id: str = Query(...),
) -> dict:
    """Manually advance a pipeline to the next state (useful after gate approval)."""
    try:
        orchestrator = _create_pipeline_orchestrator(runtime)
        _require_pipeline_access(
            orchestrator, workflow_id, current_user, organization_id
        )
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
        w
        for w in runtime.list_workflows(context)
        if (state is None or w.current_state.value == state)
    ][offset : offset + limit]

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


@router.post("/workers/claim")
def claim_pipeline_task(
    request: PipelineWorkerClaimRequest,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, object]:
    """Claim work from the queue that advances pipeline domain state."""
    queue = get_pipeline_registry(runtime).queue
    task = queue.claim_next_task(request.worker_id, request.capabilities)
    if task is None:
        return {"claimed": False, "task": None}
    metadata = dict(task.metadata or {})
    if (
        metadata.get("organization_id") != request.organization_id
        or metadata.get("actor_id") != current_user.username
    ):
        queue.fail_task(
            task.task_id,
            request.worker_id,
            "worker pipeline scope mismatch",
            retry=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Pipeline task access denied"
        )
    return {
        "claimed": True,
        "task": {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "metadata": metadata,
        },
    }


@router.post("/workers/complete")
def complete_pipeline_task(
    request: PipelineWorkerCompleteRequest,
    runtime: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, object]:
    """Complete claimed work and advance its pipeline."""
    queue = get_pipeline_registry(runtime).queue
    try:
        task = queue.get_task(request.task_id)
        metadata = dict(task.metadata or {}) if task is not None else {}
        if (
            metadata.get("organization_id") != request.organization_id
            or metadata.get("actor_id") != current_user.username
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Pipeline task access denied",
            )
        if request.success:
            queue.complete_task(
                request.task_id, request.worker_id, request.result or {}
            )
        else:
            queue.fail_task(
                request.task_id,
                request.worker_id,
                request.error or "worker failure",
                retry=False,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return {"ok": True, "task_id": request.task_id}
