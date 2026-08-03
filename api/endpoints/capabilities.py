# api/endpoints/capabilities.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import CapabilityCreate, CapabilityResponse
from domain.capability import Capability
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


def _response(cap: Capability) -> CapabilityResponse:
    return CapabilityResponse(
        id=cap.id,
        name=cap.name,
        description=cap.description,
        level=cap.level,
        certification=cap.certification,
        used_by=cap.used_by,
        created_at=cap.created_at,
        updated_at=cap.updated_at,
    )


@router.post("/", response_model=CapabilityResponse, status_code=status.HTTP_201_CREATED)
def create_capability(
    capability: CapabilityCreate,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Opret en ny Capability."""
    db_cap = Capability(
        id=capability.id,
        name=capability.name,
        description=capability.description,
        level=capability.level,
        certification=capability.certification,
    )
    return _response(dor.db_adapter.create_capability(db_cap))


@router.get("/{capability_id}", response_model=CapabilityResponse)
def get_capability(
    capability_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Hent en Capability ud fra ID."""
    cap = dor.db_adapter.get_capability(capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Capability not found")
    return _response(cap)


@router.get("/", response_model=List[CapabilityResponse])
def get_capabilities(dor: DORRuntimeDB = Depends(get_dor)):
    """Hent alle Capabilities."""
    return [_response(cap) for cap in dor.db_adapter.uow.capability.get_all()]
