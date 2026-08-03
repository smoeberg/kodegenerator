# api/endpoints/intents.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import IntentCreate, IntentResponse
from domain.intent import Intent
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/intents", tags=["intents"])


def _response(intent: Intent) -> IntentResponse:
    return IntentResponse(
        id=intent.id,
        goal=intent.goal,
        description=intent.description,
        priority=intent.priority,
        constraints=intent.constraints,
        required_capabilities=intent.required_capabilities,
        creator=intent.creator.to_dict() if intent.creator else None,
        workflow=intent.workflow.to_dict() if intent.workflow else None,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
    )


@router.post("/", response_model=IntentResponse, status_code=status.HTTP_201_CREATED)
def create_intent(intent: IntentCreate, dor: DORRuntimeDB = Depends(get_dor)):
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
        organization=organization,
    )
    return _response(dor.db_adapter.create_intent(db_intent))


@router.post("/{intent_id}/submit", response_model=IntentResponse)
def submit_intent(
    intent_id: str,
    template_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Indsend en Intent og start et Workflow."""
    intent = dor.db_adapter.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    for actor in dor.db_adapter.uow.actor.get_all():
        if not intent.matches_actor(actor):
            continue

        workflow = (
            dor.submit_intent_with_template(intent, actor, template_id)
            if template_id
            else dor.submit_intent(intent, actor)
        )
        if workflow:
            intent.workflow = workflow
            dor.db_adapter.uow.commit()
            return _response(intent)

    raise HTTPException(status_code=400, detail="No suitable actor found for intent")
