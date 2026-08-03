# api/endpoints/actors.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from api.models import ActorCreate, ActorResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.actor import Actor, ActorType

router = APIRouter(prefix="/actors", tags=["actors"])

@router.post("/", response_model=ActorResponse, status_code=status.HTTP_201_CREATED)
def create_actor(
    actor: ActorCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny Actor."""
    # Hent RoleDefinition, Department, Team (hvis angivet)
    role = dor.db_adapter.get_role_definition(actor.role_id) if actor.role_id else None
    department = dor.db_adapter.get_department(actor.department_id) if actor.department_id else None
    team = dor.db_adapter.get_team(actor.team_id) if actor.team_id else None

    # Opret Actor
    db_actor = Actor(
        id=actor.id,
        type=actor.type,
        identity=actor.identity,
        status=actor.status,
        role=role,
        department=department,
        team=team
    )

    # Tilføj Capabilities
    for cap_id in actor.capabilities:
        cap = dor.db_adapter.get_capability(cap_id)
        if cap:
            db_actor.add_capability(cap)

    # Gem i databasen
    actor_model = dor.db_adapter.create_actor(db_actor)
    return ActorResponse(
        id=actor_model.id,
        type=actor_model.type,
        identity=actor_model.identity,
        status=actor_model.status,
        role=role.to_dict() if role else None,
        department=department.to_dict() if department else None,
        team=team.to_dict() if team else None,
        capabilities=[cap.to_dict() for cap in db_actor.capabilities],
        created_at=actor_model.created_at,
        updated_at=actor_model.updated_at
    )

@router.get("/{actor_id}", response_model=ActorResponse)
def get_actor(
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en Actor ud fra ID."""
    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    return ActorResponse(
        id=actor.id,
        type=actor.type,
        identity=actor.identity,
        status=actor.status,
        role=actor.role.to_dict() if actor.role else None,
        department=actor.department.to_dict() if actor.department else None,
        team=actor.team.to_dict() if actor.team else None,
        capabilities=[cap.to_dict() for cap in actor.capabilities],
        created_at=actor.created_at if hasattr(actor, 'created_at') else None,
        updated_at=actor.updated_at if hasattr(actor, 'updated_at') else None
    )

@router.get("/", response_model=List[ActorResponse])
def get_actors(
    organization_id: Optional[str] = None,
    department_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Actors (filtreret efter organisation/afdeling)."""
    if organization_id:
        actors = dor.db_adapter.uow.actor.get_by_organization(organization_id)
    elif department_id:
        actors = dor.db_adapter.uow.actor.get_by_department(department_id)
    else:
        actors = dor.db_adapter.uow.actor.get_all()

    return [
        ActorResponse(
            id=actor.id,
            type=actor.type,
            identity=actor.identity,
            status=actor.status,
            role=actor.role.to_dict() if actor.role else None,
            department=actor.department.to_dict() if actor.department else None,
            team=actor.team.to_dict() if actor.team else None,
            capabilities=[cap.to_dict() for cap in actor.capabilities],
            created_at=actor.created_at,
            updated_at=actor.updated_at
        )
        for actor in actors
    ]
