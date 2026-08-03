# api/endpoints/role_definitions.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import RoleDefinitionCreate, RoleDefinitionResponse
from domain.role_definition import RoleDefinition
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/role-definitions", tags=["role_definitions"])


def _response(role: RoleDefinition) -> RoleDefinitionResponse:
    return RoleDefinitionResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        capabilities=role.capabilities,
        authority=role.authority,
        needs_approval_from=role.needs_approval_from,
        responsibilities=role.responsibilities,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.post("/", response_model=RoleDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_role_definition(
    role: RoleDefinitionCreate,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Opret en ny RoleDefinition."""
    db_role = RoleDefinition(
        id=role.id,
        name=role.name,
        description=role.description,
        capabilities=role.capabilities,
        authority=role.authority,
        needs_approval_from=role.needs_approval_from,
        responsibilities=role.responsibilities,
    )
    return _response(dor.db_adapter.create_role_definition(db_role))


@router.get("/{role_id}", response_model=RoleDefinitionResponse)
def get_role_definition(
    role_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Hent en RoleDefinition ud fra ID."""
    role = dor.db_adapter.get_role_definition(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="RoleDefinition not found")
    return _response(role)


@router.get("/", response_model=List[RoleDefinitionResponse])
def get_role_definitions(dor: DORRuntimeDB = Depends(get_dor)):
    """Hent alle RoleDefinitions."""
    return [_response(role) for role in dor.db_adapter.uow.role_definition.get_all()]
