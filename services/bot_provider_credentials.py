"""Encrypted tenant-scoped credentials for AI provider connections."""
from __future__ import annotations

import hashlib
from typing import Any

from services.runtime_settings import RuntimeSettingsStore

_PREFIX = "bot-provider-credential"


def _connection_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("connection_id is required")
    if len(value) > 128:
        raise ValueError("connection_id exceeds 128 characters")
    return value


def credential_setting_key(connection_id: str) -> str:
    connection_id = _connection_id(connection_id)
    digest = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()
    return f"{_PREFIX}:{digest}"


def credential_reference(connection_id: str) -> str:
    connection_id = _connection_id(connection_id)
    digest = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()
    return f"dor-runtime-settings://{_PREFIX}/{digest}"


class BotProviderCredentialStore:
    """Write-only public boundary over RuntimeSettingsStore secret encryption."""

    def __init__(self, database: Any) -> None:
        self._settings = RuntimeSettingsStore(database)

    def put(
        self,
        organization_id: str,
        connection_id: str,
        *,
        api_key: str,
        updated_by: str,
    ) -> dict[str, object]:
        organization_id = str(organization_id or "").strip()
        connection_id = _connection_id(connection_id)
        api_key = str(api_key or "").strip()
        updated_by = str(updated_by or "").strip()
        if not organization_id or not updated_by:
            raise ValueError("organization_id and updated_by are required")
        if not api_key:
            raise ValueError("api_key is required")
        self._settings.put(
            organization_id,
            credential_setting_key(connection_id),
            {
                "connection_id": connection_id,
                "kind": _PREFIX,
            },
            updated_by=updated_by,
            secret=api_key,
            keep_existing_secret=False,
        )
        return self.status(organization_id, connection_id)

    def status(self, organization_id: str, connection_id: str) -> dict[str, object]:
        organization_id = str(organization_id or "").strip()
        connection_id = _connection_id(connection_id)
        row = self._settings.get(
            organization_id, credential_setting_key(connection_id)
        )
        configured = bool(
            row
            and row.get("has_secret") is True
            and isinstance(row.get("value"), dict)
            and row["value"].get("connection_id") == connection_id
        )
        return {
            "organization_id": organization_id,
            "connection_id": connection_id,
            "credential_configured": configured,
            "secret_reference": (
                credential_reference(connection_id) if configured else None
            ),
        }

    def secret(self, organization_id: str, connection_id: str) -> str | None:
        """Internal server-only credential resolution; never expose through API."""
        return self._settings.secret(
            str(organization_id or "").strip(),
            credential_setting_key(connection_id),
        )
