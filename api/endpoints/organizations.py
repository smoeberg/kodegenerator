# api/endpoints/organizations.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import OrganizationCreate, OrganizationResponse
from domain.organization import Organization
from runtime.core import DORRuntime

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _response(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(id=org.id, name=org.name, description=org.description, created_at=org.created_at, updated_at=org.updated_at)


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(organization: OrganizationCreate, dor: DORRuntime = Depends(get_dor)):
    db_org = Organization(id=organization.id, name=organization.name, description=organization.description)
    return _response(dor.db_adapter.create_organization(db_org))


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(organization_id: str, dor: DORRuntime = Depends(get_dor)):
    org = dor.db_adapter.get_organization(organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _response(org)


@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(dor: DORRuntime = Depends(get_dor)):
    return [_response(org) for org in dor.db_adapter.uow.organization.get_all()]
