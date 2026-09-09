"""Authenticated external-integration configuration and health endpoints."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from infrastructure.persistence.models import OrganizationMembershipModel
from runtime.core import DORRuntime
from services.redmine_client import check_redmine_health
from services.runtime_settings import (
    RuntimeSettingsStore,
    SettingsEncryptionUnavailable,
    SettingsSecretUnreadable,
)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])
_REDMINE_KEY = "integration.redmine"


class RedmineConfigRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    project_id: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, max_length=4096)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise ValueError("URL'en er ugyldig") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("URL'en skal starte med http:// eller https://")
        if parsed.username or parsed.password:
            raise ValueError("Brugernavn eller adgangskode må ikke ligge i URL'en")
        return value

    @field_validator("organization_id", "project_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Værdien er påkrævet")
        return value


class RedmineConfigResponse(BaseModel):
    organization_id: str
    url: str
    project_id: str
    api_key_configured: bool
    source: str
    updated_by: str | None = None
    updated_at: datetime | None = None


def _membership(
    dor: DORRuntime,
    *,
    username: str,
    organization_id: str,
    require_admin: bool,
) -> OrganizationMembershipModel:
    with dor.database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (username, organization_id),
        )
    if membership is None or (require_admin and not membership.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": (
                    "organization_admin_required"
                    if require_admin
                    else "organization_membership_required"
                )
            },
        )
    return membership


def _effective_config(dor: DORRuntime, organization_id: str) -> dict[str, Any]:
    store = RuntimeSettingsStore(dor.database)
    row = store.get(organization_id, _REDMINE_KEY)
    env_url = os.getenv("REDMINE_URL", "").strip().rstrip("/")
    env_project = os.getenv("REDMINE_PROJECT_ID", "").strip()
    env_key = os.getenv("REDMINE_API_KEY", "").strip()
    if row is None:
        return {
            "organization_id": organization_id,
            "url": env_url,
            "project_id": env_project,
            "api_key": env_key or None,
            "api_key_configured": bool(env_key),
            "source": "environment" if (env_url or env_project or env_key) else "none",
            "updated_by": None,
            "updated_at": None,
        }
    value = row["value"]
    try:
        stored_key = store.secret(organization_id, _REDMINE_KEY)
    except (SettingsEncryptionUnavailable, SettingsSecretUnreadable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "settings_secret_unavailable", "message": str(exc)},
        ) from exc
    return {
        "organization_id": organization_id,
        "url": str(value.get("url") or "").strip().rstrip("/"),
        "project_id": str(value.get("project_id") or "").strip(),
        "api_key": stored_key or env_key or None,
        "api_key_configured": bool(stored_key or env_key),
        "source": "database",
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


def _public(config: dict[str, Any]) -> RedmineConfigResponse:
    return RedmineConfigResponse(
        organization_id=config["organization_id"],
        url=config["url"],
        project_id=config["project_id"],
        api_key_configured=config["api_key_configured"],
        source=config["source"],
        updated_by=config["updated_by"],
        updated_at=config["updated_at"],
    )


@router.get("/redmine/config", response_model=RedmineConfigResponse)
def get_redmine_config(
    organization_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> RedmineConfigResponse:
    """Return non-secret Redmine configuration for one accessible organization."""
    _membership(
        dor,
        username=current_user.username,
        organization_id=organization_id,
        require_admin=False,
    )
    return _public(_effective_config(dor, organization_id))


@router.put("/redmine/config", response_model=RedmineConfigResponse)
def put_redmine_config(
    request: RedmineConfigRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> RedmineConfigResponse:
    """Persist Redmine settings; the API key is encrypted and never echoed back."""
    _membership(
        dor,
        username=current_user.username,
        organization_id=request.organization_id,
        require_admin=True,
    )
    store = RuntimeSettingsStore(dor.database)
    try:
        store.put(
            request.organization_id,
            _REDMINE_KEY,
            {"url": request.url, "project_id": request.project_id},
            updated_by=current_user.username,
            secret=request.api_key,
            keep_existing_secret=True,
        )
    except SettingsEncryptionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "settings_encryption_not_configured",
                "message": "Systemet mangler sin krypteringsnøgle til hemmelige indstillinger.",
            },
        ) from exc
    return _public(_effective_config(dor, request.organization_id))


@router.post("/redmine/test")
def test_redmine_connection(
    organization_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    """Test the saved configuration without returning credentials or upstream payloads."""
    _membership(
        dor,
        username=current_user.username,
        organization_id=organization_id,
        require_admin=False,
    )
    config = _effective_config(dor, organization_id)
    return check_redmine_health(
        base_url=config["url"],
        api_key=config["api_key"],
        project_id=config["project_id"],
    )


@router.get("/redmine/health")
def redmine_health(
    organization_id: str | None = None,
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    """Verify Redmine without exposing credentials; env fallback remains migration-safe."""
    if not organization_id:
        return check_redmine_health()
    config = _effective_config(dor, organization_id)
    return check_redmine_health(
        base_url=config["url"],
        api_key=config["api_key"],
        project_id=config["project_id"],
    )
