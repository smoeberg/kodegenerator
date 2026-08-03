# api/endpoints/capabilities.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import CapabilityCreate, CapabilityResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.capability import Capability, CapabilityLevel

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

@router.post("/", response_model=CapabilityResponse, status_code=status.HTTP_201_CREATED)
def create_capability(
    capability: CapabilityCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny Capability."""
    db_cap = Capability(
        id=capability.id,
        name=capability.name,
        description=capability.description,
        level=capability.level,
        certification=capability.certification
    )
    cap_model = dor.db_adapter.create_capability(db_cap)
    return CapabilityResponse(
        id=cap_model.id,
        name=cap_model.name,
        description=cap_model.description,
        level=cap_model.level,
        certification=cap_model.certification,
        used_by=cap_model.used_by,
        created_at=cap_model.created_at,
        updated_at=cap_model.updated_at
    )

@router.get("/{capability_id}", response_model=CapabilityResponse)
def get_capability(
    capability_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en Capability ud fra ID."""
    cap = dor.db_adapter.get_capability(capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Capability not found")
    return CapabilityResponse(
        id=cap.id,
        name=cap.name,
        description=cap.description,
        level=cap.level,
        certification=cap.certification,
        used_by=cap.used_by,
        created_at=cap.created_at,
        updated_at=cap.updated_at
    )

@router.get("/", response_model=List[CapabilityResponse])
def get_capabilities(
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Capabilities."""
    caps = dor.db_adapter.uow.capability.get_all()
    return [
        CapabilityResponse(
            id=cap.id,
            name=cap.name,
            description=cap.description,
            level=cap.level,
            certification=cap.certification,
            used_by=cap.used_by,
            created_at=cap.created_at,
            updated_at=cap.updated_at
        )
        for cap in caps
    ]
