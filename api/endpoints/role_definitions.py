# api/endpoints/role_definitions.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import RoleDefinitionCreate, RoleDefinitionResponse
from domain.authority import RoleDefinition
from runtime.core import DORRuntime

router = APIRouter(prefix="/role-definitions", tags=["role_definitions"])


def _response(role: RoleDefinition) -> RoleDefinitionResponse:
    return RoleDefinitionResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        capabilities=role.capabilities,
        authority=getattr(role, "authority", {}),
        needs_approval_from=getattr(role, "needs_approval_from", {}),
        responsibilities=getattr(role, "responsibilities", []),
        created_at=getattr(role, "created_at", None),
        updated_at=getattr(role, "updated_at", None),
    )


@router.post("/", response_model=RoleDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_role_definition(role: RoleDefinitionCreate, dor: DORRuntime = Depends(get_dor)):
    db_role = RoleDefinition(
        id=role.id,
        name=role.name,
        organization_id=role.organization_id,
        description=role.description,
        capabilities=frozenset(role.capabilities),
    )
    return _response(dor.db_adapter.create_role_definition(db_role))


@router.get("/{role_id}", response_model=RoleDefinitionResponse)
def get_role_definition(role_id: str, organization_id: str, dor: DORRuntime = Depends(get_dor)):
    role = dor.db_adapter.get_role_definition(role_id, organization_id)
    if not role:
        raise HTTPException(status_code=404, detail="RoleDefinition not found")
    return _response(role)


@router.get("/", response_model=List[RoleDefinitionResponse])
def get_role_definitions(dor: DORRuntime = Depends(get_dor)):
    return [_response(role) for role in dor.db_adapter.uow.role_definition.get_all()]
