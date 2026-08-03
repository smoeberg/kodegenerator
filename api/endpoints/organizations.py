# api/endpoints/organizations.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import OrganizationCreate, OrganizationResponse
from domain.organization import Organization
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _response(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        description=org.description,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    organization: OrganizationCreate,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Opret en ny organisation."""
    db_org = Organization(
        id=organization.id,
        name=organization.name,
        description=organization.description,
    )
    return _response(dor.db_adapter.create_organization(db_org))


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Hent en organisation ud fra ID."""
    org = dor.db_adapter.get_organization(organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _response(org)


@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(dor: DORRuntimeDB = Depends(get_dor)):
    """Hent alle organisationer."""
    return [_response(org) for org in dor.db_adapter.uow.organization.get_all()]
