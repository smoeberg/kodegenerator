"""Canonical pipeline gate approval endpoints.

These endpoints let a human approver approve a pending pipeline gate
(requirements / architecture / contracts / release) so the orchestrator can
advance the pipeline.

Note: this is intentionally separate from the Decision Engine
(api/endpoints/decisions.py) — gates are pipeline checkpoints, decisions are
agent deliberations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from domain.principal import Principal
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import get_pipeline_registry

router = APIRouter(prefix="/api/v1/pipeline-gates", tags=["pipeline_gates"])


class ApproveGateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=256)
    gate_id: str = Field(min_length=1, max_length=256)
    decision: str = Field(default="approved", pattern="^(approved|rejected)$")


class GateApprovalResponse(BaseModel):
    workflow_id: str
    gate_id: str
    approved: bool
    status: Optional[str] = None


def _context(dor: DORRuntime, current_user: User, organization_id: str):
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"username": current_user.username},
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
            detail="Organization access denied",
        ) from exc


def _orchestrator(dor: DORRuntime, organization_id: str) -> PipelineOrchestrator:
    return get_pipeline_registry(dor, organization_id=organization_id).orchestrator


def _workflow_or_404(
    orch: PipelineOrchestrator,
    workflow_id: str,
    organization_id: str,
):
    workflow = orch._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
        )
    return workflow


@router.post(
    "/approve", response_model=GateApprovalResponse, status_code=status.HTTP_200_OK
)
def approve_gate(
    request: ApproveGateRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
    organization_id: str = Query(...),
) -> GateApprovalResponse:
    _context(dor, current_user, organization_id)
    orch = _orchestrator(dor, organization_id)
    workflow = _workflow_or_404(orch, request.workflow_id, organization_id)
    try:
        approved = orch.approve_gate(
            request.workflow_id,
            request.gate_id,
            approver=current_user.username,
            decision=request.decision,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return GateApprovalResponse(
        workflow_id=request.workflow_id,
        gate_id=request.gate_id,
        approved=approved,
        status=workflow.current_state.value,
    )


@router.get("/{workflow_id}", response_model=List[Dict[str, Any]])
def list_gates(
    workflow_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
    organization_id: str = Query(...),
) -> List[Dict[str, Any]]:
    _context(dor, current_user, organization_id)
    orch = _orchestrator(dor, organization_id)
    workflow = _workflow_or_404(orch, workflow_id, organization_id)
    pending_gate_ids = {
        transition.gate_id
        for transition in workflow.transitions
        if transition.from_state == workflow.current_state and transition.gate_id
    }
    return [
        {
            "id": gate.id,
            "name": gate.name,
            "description": gate.description,
            "resolved": gate.decision_id is not None,
            "pending": gate.id in pending_gate_ids and gate.decision_id is None,
        }
        for gate in workflow.gates
    ]
