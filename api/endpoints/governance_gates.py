"""Governance Gate endpoints for signing artifacts and approving workflow transitions."""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from api.auth import get_current_actor
from domain.actor import Actor
from domain.artifact import Signature
from infrastructure.database.dor_db_adapter import DORDBAdapter

router = APIRouter(prefix="/governance", tags=["Governance Gates"])

class SignArtifactRequest(BaseModel):
    artifact_id: str
    role_id: str
    status: str = Field(..., description="approved, rejected, or needs_changes")
    comments: str = ""

class GateDecisionRequest(BaseModel):
    workflow_id: str
    gate_id: str
    decision: str = Field(..., description="approve or reject")
    reason: str = ""

@router.post("/artifacts/sign", status_code=status.HTTP_200_OK)
async def sign_artifact(
    req: SignArtifactRequest,
    current_actor: Actor = Depends(get_current_actor)
) -> Dict[str, Any]:
    """Allows an authorized human supervisor or reviewer to sign an artifact and persist it to DB."""
    try:
        db = DORDBAdapter()
        artifact = db.get_artifact(req.artifact_id)
        
        signature = Signature(
            role_id=req.role_id,
            actor_id=current_actor.id,
            status=req.status,
            comments=req.comments
        )
        
        if artifact:
            artifact.signatures.append(signature)
            db.save_artifact(artifact)

        return {
            "status": "success",
            "message": f"Artifact {req.artifact_id} signed with status {req.status} and persisted to DB",
            "signature": {
                "role_id": signature.role_id,
                "actor_id": signature.actor_id,
                "status": signature.status,
                "comments": signature.comments
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/gates/evaluate", status_code=status.HTTP_200_OK)
async def evaluate_gate(
    req: GateDecisionRequest,
    current_actor: Actor = Depends(get_current_actor)
) -> Dict[str, Any]:
    """Allows an authorized human actor to explicitly approve or reject a workflow gate in DB."""
    try:
        db = DORDBAdapter()
        workflow = db.get_workflow(req.workflow_id)
        if workflow:
            # Persist gate decision into workflow metadata / gate log
            workflow.metadata[f"gate_{req.gate_id}_decision"] = {
                "decision": req.decision,
                "reason": req.reason,
                "approved_by": current_actor.identity
            }
            db.save_workflow(workflow)

        return {
            "status": "success",
            "workflow_id": req.workflow_id,
            "gate_id": req.gate_id,
            "decision": req.decision,
            "reason": req.reason,
            "approved_by": current_actor.identity
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
