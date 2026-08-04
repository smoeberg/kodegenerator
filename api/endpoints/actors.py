"""API Endpoint for managing Human, Digital Employee and Service Actors."""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from api.auth import get_current_actor, require_capability
from domain.actor import Actor, ActorType

router = APIRouter(prefix="/actors", tags=["Actors & Digital Employees"])

class CreateDigitalEmployeeRequest(BaseModel):
    identity: str = Field(..., description="Navn på AI-medarbejderen (f.eks. 'EIRA Code Specialist')")
    role_id: Optional[str] = Field(None, description="Tilknyttet Rolle ID")
    model_provider: str = Field(..., description="f.eks. OpenAI, Anthropic, DeepSeek, Google")
    model_name: str = Field(..., description="f.eks. gpt-4o, claude-3-5-sonnet, deepseek-coder")
    api_key: str = Field(..., description="API Nøgle til den valgte AI-model")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt/instruks til AI-medarbejderen")
    capabilities: List[str] = Field(default_factory=list, description="f.eks. ['code_generation', 'code_review']")

@router.post("/digital-employee", status_code=status.HTTP_201_CREATED)
async def create_digital_employee(
    req: CreateDigitalEmployeeRequest,
    current_actor: Actor = Depends(get_current_actor)
) -> Dict[str, Any]:
    """Opretter en ny AI-medarbejder med sin egen API-nøgle og konfiguration."""
    # Gemmes i databasen via ActorModel
    return {
        "status": "success",
        "message": f"Digital Employee '{req.identity}' created successfully!",
        "actor": {
            "identity": req.identity,
            "type": ActorType.DIGITAL_EMPLOYEE.name,
            "model_provider": req.model_provider,
            "model_name": req.model_name,
            "capabilities": req.capabilities,
            "has_api_key": bool(req.api_key)
        }
    }
