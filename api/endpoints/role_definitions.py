# api/endpoints/role_definitions.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import RoleDefinitionCreate, RoleDefinitionResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.role_definition import RoleDefinition

router = APIRouter(prefix="/role-definitions", tags=["role_definitions"])

@router.post("/", response_model=RoleDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_role_definition(
    role: RoleDefinitionCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny RoleDefinition."""
    db_role = RoleDefinition(
        id=role.id,
        name=role.name,
        description=role.description,
        capabilities=role.capabilities,
        authority=role.authority,
        needs_approval_from=role.needs_approval_from,
        responsibilities=role.responsibilities
    )
    role_model = dor.db_adapter.create_role_definition(db_role)
    return RoleDefinitionResponse(
        id=role_model.id,
        name=role_model.name,
        description=role_model.description,
        capabilities=role_model.capabilities,
        authority=role_model.authority,
        needs_approval_from=role_model.needs_approval_from,
        responsibilities=role_model.responsibilities,
        created_at=role_model.created_at,
        updated_at=role_model.updated_at
    )

@router.get("/{role_id}", response_model=RoleDefinitionResponse)
def get_role_definition(
    role_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en RoleDefinition ud fra ID."""
    role = dor.db_adapter.get_role_definition(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="RoleDefinition not found")
    return RoleDefinitionResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        capabilities=role.capabilities,
        authority=role.authority,
        needs_approval_from=role.needs_approval_from,
        responsibilities=role.responsibilities,
        created_at=role.created_at,
        updated_at=role.updated_at
    )
