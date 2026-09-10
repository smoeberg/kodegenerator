"""Fail-closed administration visibility derived from authoritative backend state."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class OrganizationCatalogClient(Protocol):
    def get(self, path: str, **kwargs: Any) -> Any: ...


def resolve_organization_admin_status(
    payload: Any,
    organization_id: str | None,
) -> bool | None:
    """Return explicit backend admin status for one organization.

    ``None`` means the authorization projection is missing, malformed or does not
    contain the selected organization.  Callers must treat that state as unknown
    and must not expose administrative mutation capabilities.
    """
    target = str(organization_id or "").strip()
    if not target or not isinstance(payload, Mapping):
        return None

    organizations = payload.get("organizations")
    if not isinstance(organizations, list):
        return None

    for item in organizations:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("id") or "").strip() != target:
            continue
        value = item.get("is_admin")
        if value is True:
            return True
        if value is False:
            return False
        return None
    return None


def fetch_organization_admin_status(
    client: OrganizationCatalogClient,
    organization_id: str | None,
) -> bool | None:
    """Refresh admin visibility from the canonical organization catalog."""
    payload = client.get("/api/v1/control-plane/organizations")
    return resolve_organization_admin_status(payload, organization_id)
