"""Authenticated external-integration health endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from services.redmine_client import check_redmine_health

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/redmine/health")
def redmine_health() -> dict[str, Any]:
    """Verify server-side Redmine configuration without exposing credentials."""
    return check_redmine_health()
