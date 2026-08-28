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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from runtime.core import DORRuntime
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


def _orchestrator(dor: DORRuntime) -> PipelineOrchestrator:
    # Reuse a per-runtime orchestrator when available; otherwise create one.
    if (
        hasattr(dor, "_pipeline_orchestrator")
        and dor._pipeline_orchestrator is not None
    ):
        return dor._pipeline_orchestrator
    orch = get_pipeline_registry(dor).orchestrator
    if hasattr(dor, "_pipeline_orchestrator"):
        dor._pipeline_orchestrator = orch
    return orch


@router.post(
    "/approve", response_model=GateApprovalResponse, status_code=status.HTTP_200_OK
)
def approve_gate(
    request: ApproveGateRequest,
    _: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> GateApprovalResponse:
    orch = _orchestrator(dor)
    try:
        approved = orch.approve_gate(
            request.workflow_id,
            request.gate_id,
            approver=_.username,
            decision=request.decision,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    workflow = orch._get_workflow(request.workflow_id)
    return GateApprovalResponse(
        workflow_id=request.workflow_id,
        gate_id=request.gate_id,
        approved=approved,
        status=workflow.current_state.value if workflow else None,
    )


@router.get("/{workflow_id}", response_model=List[Dict[str, Any]])
def list_gates(
    workflow_id: str,
    _: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> List[Dict[str, Any]]:
    orch = _orchestrator(dor)
    workflow = orch._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found"
        )
    return [
        {
            "id": gate.id,
            "name": gate.name,
            "description": gate.description,
            "resolved": gate.decision_id is not None,
        }
        for gate in workflow.gates
    ]
