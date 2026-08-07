"""API Endpoint for managing Human, Digital Employee and Service Actors."""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from api.auth import get_current_actor
from domain.actor import Actor, ActorType

router = APIRouter(prefix="/actors", tags=["Actors & Digital Employees"])


class CreateDigitalEmployeeRequest(BaseModel):
    identity: str = Field(..., description="Navn på AI-medarbejderen")
    role_id: Optional[str] = Field(None, description="Tilknyttet Rolle ID")
    model_provider: str = Field(..., description="AI provider")
    model_name: str = Field(..., description="AI model")
    api_key: str = Field(..., description="API Nøgle til den valgte AI-model")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt")
    capabilities: List[str] = Field(default_factory=list)


@router.post("/digital-employee", status_code=status.HTTP_201_CREATED)
async def create_digital_employee(
    req: CreateDigitalEmployeeRequest,
    current_actor: Actor = Depends(get_current_actor),
) -> Dict[str, Any]:
    """Return the requested actor configuration without claiming persistence.

    Persistence of digital employees belongs to the canonical runtime persistence
    boundary and is intentionally not implemented through the legacy API adapter.
    """
    return {
        "status": "accepted",
        "message": f"Digital Employee '{req.identity}' configuration accepted",
        "actor": {
            "identity": req.identity,
            "type": ActorType.DIGITAL_EMPLOYEE.name,
            "model_provider": req.model_provider,
            "model_name": req.model_name,
            "capabilities": req.capabilities,
            "has_api_key": bool(req.api_key),
            "created_by": current_actor.id,
            "persisted": False,
        },
    }
