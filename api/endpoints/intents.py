# api/endpoints/intents.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import IntentCreate, IntentResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.intent import Intent, IntentPriority

router = APIRouter(prefix="/intents", tags=["intents"])

@router.post("/", response_model=IntentResponse, status_code=status.HTTP_201_CREATED)
def create_intent(
    intent: IntentCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny Intent."""
    creator = dor.db_adapter.get_actor(intent.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    organization = dor.db_adapter.get_organization(intent.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    db_intent = Intent(
        id=intent.id,
        goal=intent.goal,
        description=intent.description,
        priority=intent.priority,
        constraints=intent.constraints,
        required_capabilities=intent.required_capabilities,
        creator=creator,
        organization=organization
    )
    intent_model = dor.db_adapter.create_intent(db_intent)
    return IntentResponse(
        id=intent_model.id,
        goal=intent_model.goal,
        description=intent_model.description,
        priority=intent_model.priority,
        constraints=intent_model.constraints,
        required_capabilities=intent_model.required_capabilities,
        creator=creator.to_dict() if creator else None,
        workflow=None,  # Vil blive sat, når workflow oprettes
        created_at=intent_model.created_at,
        updated_at=intent_model.updated_at
    )

@router.post("/{intent_id}/submit", response_model=IntentResponse)
def submit_intent(
    intent_id: str,
    template_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Indsend en Intent og start et Workflow."""
    intent = dor.db_adapter.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    # Find en Actor, der kan håndtere Intent (simplificeret: brug den første Actor med de nødvendige Capabilities)
    actors = dor.db_adapter.uow.actor.get_all()
    for actor in actors:
        if intent.matches_actor(actor):
            if template_id:
                workflow = dor.submit_intent_with_template(intent, actor, template_id)
            else:
                workflow = dor.submit_intent(intent, actor)
            if workflow:
                # Opdater Intent med Workflow
                intent.workflow = workflow
                dor.db_adapter.uow.commit()
                return IntentResponse(
                    id=intent.id,
                    goal=intent.goal,
                    description=intent.description,
                    priority=intent.priority,
                    constraints=intent.constraints,
                    required_capabilities=intent.required_capabilities,
                    creator=intent.creator.to_dict() if intent.creator else None,
                    workflow=workflow.to_dict() if workflow else None,
                    created_at=intent.created_at,
                    updated_at=intent.updated_at
                )
    raise HTTPException(status_code=400, detail="No suitable actor found for intent")
