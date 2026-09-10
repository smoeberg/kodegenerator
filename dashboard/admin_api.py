"""Authoritative HTTP contracts used by the standalone GUI-03 admin surface.

The facade contains transport conveniences only.  It deliberately does not
model permissions, configuration or integration state locally: every value is
read from, and every mutation is confirmed by, the canonical FastAPI API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dashboard.api_client import DORAPIClient


@dataclass(frozen=True)
class AdminCapability:
    key: str
    label: str
    support: str
    detail: str


# This is an explicit map of API contracts present in the repository.  Missing
# contracts remain visible as limitations on the overview, never as fake forms.
CAPABILITIES: tuple[AdminCapability, ...] = (
    AdminCapability("organizations", "Organisationer", "implemented", "Liste, opret og rediger via Control Plane API."),
    AdminCapability("users", "Brugere", "implemented", "Organisation-scoped brugeradministration med server-side admin-check."),
    AdminCapability("projects", "Projekter", "read-only", "Projektkatalog kan inspiceres; lifecycle forbliver i Operator/Case Journey."),
    AdminCapability("redmine", "Redmine", "implemented", "Konfiguration, hemmelig credential og forbindelsestest via backend."),
    AdminCapability("implementation_ai", "Implementation AI", "implemented", "Model/endpoint/credential kan administreres via backend."),
    AdminCapability("system_health", "System health", "implemented", "Liveness og database-readiness fra backend."),
    AdminCapability("roles", "Roller & permissions", "limited", "Backend eksponerer kun organisationens admin-medlemskab; intet generisk RBAC-admin API."),
    AdminCapability("audit", "Audit", "unsupported", "Ingen authoritative administrativ audit-query kontrakt er eksponeret."),
    AdminCapability("departments", "Afdelinger", "unsupported", "Ingen backend-kontrakt fundet."),
    AdminCapability("repository_mapping", "Repository mappings", "unsupported", "Ingen administrativ mapping-kontrakt fundet."),
    AdminCapability("notifications", "Notifikationer", "unsupported", "Ingen administrativ notification-kontrakt fundet."),
    AdminCapability("security_config", "Security configuration", "read-only", "Security håndhæves server-side; ingen sikker mutable admin-kontrakt er eksponeret."),
)


class AdminAPI:
    """Small GUI-03 facade around :class:`DORAPIClient`."""

    def __init__(self, client: DORAPIClient):
        self.client = client

    def health(self) -> dict[str, Any]:
        return self.client.health()

    def readiness(self) -> dict[str, Any]:
        return self.client.readiness()

    def organizations(self) -> dict[str, Any]:
        return self.client.get("/api/v1/control-plane/organizations")

    def create_organization(self, *, organization_id: str, name: str, description: str) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/control-plane/organizations",
            json={"id": organization_id, "name": name, "description": description},
        )

    def update_organization(self, organization_id: str, *, name: str, description: str) -> dict[str, Any]:
        return self.client.patch(
            f"/api/v1/control-plane/organizations/{organization_id}",
            json={"name": name, "description": description},
        )

    def projects(self, organization_id: str) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/control-plane/projects",
            params={"organization_id": organization_id},
        )

    def users(self, organization_id: str) -> list[dict[str, Any]]:
        return self.client.get(
            f"/api/v1/control-plane/organizations/{organization_id}/users"
        )

    def create_user(
        self,
        organization_id: str,
        *,
        username: str,
        password: str,
        email: str | None,
        full_name: str | None,
        is_admin: bool,
    ) -> dict[str, Any]:
        return self.client.post(
            f"/api/v1/control-plane/organizations/{organization_id}/users",
            json={
                "username": username,
                "password": password,
                "email": email or None,
                "full_name": full_name or None,
                "is_admin": is_admin,
            },
        )

    def update_user(
        self,
        organization_id: str,
        username: str,
        *,
        email: str | None = None,
        full_name: str | None = None,
        password: str | None = None,
        disabled: bool | None = None,
        is_admin: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in (
            ("email", email),
            ("full_name", full_name),
            ("password", password),
            ("disabled", disabled),
            ("is_admin", is_admin),
        ):
            if value is not None:
                payload[key] = value
        return self.client.patch(
            f"/api/v1/control-plane/organizations/{organization_id}/users/{username}",
            json=payload,
        )

    def redmine_config(self, organization_id: str) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/integrations/redmine/config",
            params={"organization_id": organization_id},
        )

    def save_redmine(
        self,
        organization_id: str,
        *,
        url: str,
        project_id: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "organization_id": organization_id,
            "url": url,
            "project_id": project_id,
        }
        # Empty means "keep existing secret" in the backend contract.
        if api_key:
            payload["api_key"] = api_key
        return self.client.put("/api/v1/integrations/redmine/config", json=payload)

    def test_redmine(self, organization_id: str) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/integrations/redmine/test",
            params={"organization_id": organization_id},
        )

    def ai_config(self, organization_id: str) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/integrations/ai/config",
            params={"organization_id": organization_id},
        )

    def save_ai(
        self,
        organization_id: str,
        *,
        model: str,
        base_url: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "organization_id": organization_id,
            "model": model,
            "base_url": base_url,
        }
        if api_key:
            payload["api_key"] = api_key
        return self.client.put("/api/v1/integrations/ai/config", json=payload)

    def test_ai(self, organization_id: str) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/integrations/ai/test",
            params={"organization_id": organization_id},
        )
