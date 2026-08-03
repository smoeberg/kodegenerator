# api/endpoints/organizations.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from api.models import OrganizationCreate, OrganizationResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.organization import Organization

router = APIRouter(prefix="/organizations", tags=["organizations"])

@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    organization: OrganizationCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny Organisation."""
    db_org = Organization(
        id=organization.id,
        name=organization.name,
        description=organization.description
    )
    # Gem i databasen
    org_model = dor.db_adapter.create_organization(db_org)
    return OrganizationResponse(
        id=org_model.id,
        name=org_model.name,
        description=org_model.description,
        created_at=org_model.created_at,
        updated_at=org_model.updated_at
    )

@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en Organisation ud fra ID."""
    org = dor.db_adapter.get_organization(organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        description=org.description,
        created_at=org.created_at,
        updated_at=org.updated_at
    )

@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Organisationer."""
    orgs = dor.db_adapter.uow.organization.get_all()
    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            description=org.description,
            created_at=org.created_at,
            updated_at=org.updated_at
        )
        for org in orgs
    ]
