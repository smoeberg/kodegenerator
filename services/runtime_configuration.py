"""Fail-closed configuration contract for hardened DOR runtime roles."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from urllib.parse import urlparse

from cryptography.fernet import Fernet

HARDENED_ENVIRONMENTS = frozenset({"production"})
RUNTIME_ROLES = frozenset({"api", "dashboard", "migrate", "worker"})
_PLACEHOLDER_FRAGMENTS = (
    "change-me",
    "generated-",
    "placeholder",
    "replace-with",
)
_COMMON_REQUIRED = (
    "ARTIFACT_BUCKET",
    "ARTIFACT_STORE_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
    "DOR_AUTHORITY_SIGNING_KEY",
    "DOR_ENCRYPTION_KEY",
    "DOR_IDENTITY_DATABASE_URL",
    "DOR_JWT_ACTIVE_KEY_ID",
    "DOR_JWT_SIGNING_KEYS",
    "DOR_PIPELINE_DATABASE_URL",
    "DOR_PIPELINE_STATE_ORGANIZATION_ID",
    "DOR_QUEUE_BACKEND",
)
_ROLE_REQUIRED = {
    "api": (
        "DOR_ADMIN_ORGANIZATION_ID",
        "DOR_ADMIN_PASSWORD",
        "DOR_ADMIN_USERNAME",
    ),
    "dashboard": ("DOR_ADMIN_PASSWORD", "DOR_API_BASE"),
    "migrate": (
        "DOR_WORKER_CAPABILITIES",
        "DOR_WORKER_CREDENTIAL",
        "DOR_WORKER_ORGANIZATION_ID",
        "DOR_WORKER_SERVICE_ID",
    ),
    "worker": (
        "DOR_WORKER_CAPABILITIES",
        "DOR_WORKER_CREDENTIAL",
        "DOR_WORKER_ORGANIZATION_ID",
        "DOR_WORKER_SERVICE_ID",
    ),
}
_SECRET_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DOR_ADMIN_PASSWORD",
    "DOR_AUTHORITY_SIGNING_KEY",
    "DOR_ENCRYPTION_KEY",
    "DOR_JWT_SIGNING_KEYS",
    "DOR_WORKER_CREDENTIAL",
)


class RuntimeConfigurationError(RuntimeError):
    """A hardened process would start with unsafe or inconsistent wiring."""


def validate_runtime_configuration(
    environment: Mapping[str, str] | None = None,
    *,
    role: str | None = None,
) -> None:
    """Validate one process role without exposing configured secret values."""
    values = os.environ if environment is None else environment
    dor_environment = values.get("DOR_ENV", "development").strip().lower()
    if dor_environment not in HARDENED_ENVIRONMENTS:
        return

    runtime_role = (role or values.get("DOR_RUNTIME_ROLE", "")).strip().lower()
    if runtime_role not in RUNTIME_ROLES:
        raise RuntimeConfigurationError(
            "DOR_RUNTIME_ROLE must identify api, dashboard, migrate, or worker"
        )
    required = (*_COMMON_REQUIRED, *_ROLE_REQUIRED[runtime_role])
    missing = sorted(name for name in required if not values.get(name, "").strip())
    if missing:
        raise RuntimeConfigurationError(
            "Missing required hardened runtime configuration: " + ", ".join(missing)
        )

    database_urls = {
        name: values[name].strip()
        for name in (
            "DATABASE_URL",
            "DOR_IDENTITY_DATABASE_URL",
            "DOR_PIPELINE_DATABASE_URL",
        )
    }
    if any(not value.startswith("postgresql+") for value in database_urls.values()):
        raise RuntimeConfigurationError(
            "Hardened runtime database URLs must use PostgreSQL SQLAlchemy drivers"
        )
    if len(set(database_urls.values())) != 1:
        raise RuntimeConfigurationError(
            "Identity, pipeline, and canonical runtime must share DATABASE_URL"
        )
    if values["DOR_QUEUE_BACKEND"].strip().lower() != "database":
        raise RuntimeConfigurationError(
            "Hardened runtime requires DOR_QUEUE_BACKEND=database"
        )

    _validate_url(values["ARTIFACT_STORE_URL"], "ARTIFACT_STORE_URL")
    if runtime_role == "dashboard":
        _validate_url(values["DOR_API_BASE"], "DOR_API_BASE")
    for name in _SECRET_NAMES:
        value = values.get(name, "").strip()
        if value:
            _reject_placeholder(name, value)
    if len(values["DOR_AUTHORITY_SIGNING_KEY"].strip()) < 32:
        raise RuntimeConfigurationError(
            "DOR_AUTHORITY_SIGNING_KEY must contain at least 32 characters"
        )
    if (
        runtime_role in {"migrate", "worker"}
        and len(values["DOR_WORKER_CREDENTIAL"].strip()) < 32
    ):
        raise RuntimeConfigurationError(
            "DOR_WORKER_CREDENTIAL must contain at least 32 characters"
        )
    try:
        Fernet(values["DOR_ENCRYPTION_KEY"].strip().encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise RuntimeConfigurationError(
            "DOR_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc
    _validate_jwt_keyring(values)


def _validate_jwt_keyring(values: Mapping[str, str]) -> None:
    try:
        keys = json.loads(values["DOR_JWT_SIGNING_KEYS"])
    except json.JSONDecodeError as exc:
        raise RuntimeConfigurationError(
            "DOR_JWT_SIGNING_KEYS must be valid JSON"
        ) from exc
    if not isinstance(keys, dict) or not keys:
        raise RuntimeConfigurationError(
            "DOR_JWT_SIGNING_KEYS must be a non-empty JSON object"
        )
    active = values["DOR_JWT_ACTIVE_KEY_ID"].strip()
    if active not in keys:
        raise RuntimeConfigurationError(
            "DOR_JWT_ACTIVE_KEY_ID must reference a configured signing key"
        )
    if any(not isinstance(value, str) or len(value) < 32 for value in keys.values()):
        raise RuntimeConfigurationError(
            "Every hardened JWT signing key must contain at least 32 characters"
        )


def _validate_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeConfigurationError(f"{name} must be an absolute HTTP(S) URL")


def _reject_placeholder(name: str, value: str) -> None:
    lowered = value.lower()
    if any(fragment in lowered for fragment in _PLACEHOLDER_FRAGMENTS):
        raise RuntimeConfigurationError(f"{name} contains a forbidden placeholder")
