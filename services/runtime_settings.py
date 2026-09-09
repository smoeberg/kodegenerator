"""Tenant-scoped operational settings persisted by the DOR API.

Ordinary configuration belongs behind authenticated API surfaces rather than in
browser-visible environment files. Secret values are encrypted before they are
written and are never returned by this store unless an internal server caller
explicitly requests decryption.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text


class SettingsEncryptionUnavailable(RuntimeError):
    """Raised when the deployment has no root key for protecting stored secrets."""


class SettingsSecretUnreadable(RuntimeError):
    """Raised when persisted ciphertext cannot be decrypted with the current root key."""


def _fernet() -> Fernet:
    raw = os.getenv("DOR_SETTINGS_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise SettingsEncryptionUnavailable(
            "DOR_SETTINGS_ENCRYPTION_KEY is required before secrets can be saved"
        )
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt_secret(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("secret value is required")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SettingsSecretUnreadable(
            "stored setting cannot be decrypted with the active settings key"
        ) from exc


class RuntimeSettingsStore:
    """Small tenant-aware store over the migrated ``runtime_settings`` table."""

    def __init__(self, database: Any) -> None:
        self._database = database

    def get(self, organization_id: str, setting_key: str) -> dict[str, Any] | None:
        with self._database.session(organization_id) as session:
            row = session.execute(
                text(
                    "SELECT value_json, secret_ciphertext, updated_by, updated_at "
                    "FROM runtime_settings "
                    "WHERE organization_id = :organization_id AND setting_key = :setting_key"
                ),
                {"organization_id": organization_id, "setting_key": setting_key},
            ).mappings().first()
        if row is None:
            return None
        try:
            value = json.loads(row["value_json"] or "{}")
        except (TypeError, ValueError):
            value = {}
        return {
            "organization_id": organization_id,
            "setting_key": setting_key,
            "value": value if isinstance(value, dict) else {},
            "has_secret": bool(row["secret_ciphertext"]),
            "secret_ciphertext": row["secret_ciphertext"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }

    def secret(self, organization_id: str, setting_key: str) -> str | None:
        row = self.get(organization_id, setting_key)
        if row is None or not row["secret_ciphertext"]:
            return None
        return decrypt_secret(str(row["secret_ciphertext"]))

    def put(
        self,
        organization_id: str,
        setting_key: str,
        value: Mapping[str, Any],
        *,
        updated_by: str,
        secret: str | None = None,
        keep_existing_secret: bool = True,
    ) -> dict[str, Any]:
        existing = self.get(organization_id, setting_key)
        ciphertext: str | None
        if secret is not None and str(secret).strip():
            ciphertext = encrypt_secret(secret)
        elif keep_existing_secret and existing is not None:
            ciphertext = existing["secret_ciphertext"]
        else:
            ciphertext = None
        now = datetime.now(timezone.utc)
        payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
        with self._database.session(organization_id) as session, session.begin():
            current = session.execute(
                text(
                    "SELECT 1 FROM runtime_settings "
                    "WHERE organization_id = :organization_id AND setting_key = :setting_key"
                ),
                {"organization_id": organization_id, "setting_key": setting_key},
            ).first()
            params = {
                "organization_id": organization_id,
                "setting_key": setting_key,
                "value_json": payload,
                "secret_ciphertext": ciphertext,
                "updated_by": updated_by,
                "updated_at": now,
            }
            if current is None:
                session.execute(
                    text(
                        "INSERT INTO runtime_settings "
                        "(organization_id, setting_key, value_json, secret_ciphertext, updated_by, updated_at) "
                        "VALUES (:organization_id, :setting_key, :value_json, :secret_ciphertext, :updated_by, :updated_at)"
                    ),
                    params,
                )
            else:
                session.execute(
                    text(
                        "UPDATE runtime_settings SET value_json = :value_json, "
                        "secret_ciphertext = :secret_ciphertext, updated_by = :updated_by, "
                        "updated_at = :updated_at WHERE organization_id = :organization_id "
                        "AND setting_key = :setting_key"
                    ),
                    params,
                )
        result = self.get(organization_id, setting_key)
        if result is None:  # pragma: no cover - defensive persistence guard
            raise RuntimeError("runtime setting was not persisted")
        return result
