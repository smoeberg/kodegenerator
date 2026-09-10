"""Organization-scoped implementation-AI settings and connectivity checks."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from services.runtime_settings import (
    RuntimeSettingsStore,
    SettingsEncryptionUnavailable,
    SettingsSecretUnreadable,
)
from services.secure_http import validate_http_url

IMPLEMENTATION_AI_SETTING_KEY = "system.ai.implementation"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_MAX_PROBE_BYTES = 2 * 1024 * 1024

OpenURL = Callable[[urllib.request.Request, float], Any]


def normalize_openai_base_url(value: str) -> str:
    """Validate one admin-owned OpenAI-compatible API base URL."""
    normalized = str(value or "").strip().rstrip("/")
    validate_http_url(normalized)
    parsed = urlparse(normalized)
    if parsed.username or parsed.password:
        raise ValueError("AI-endpoint må ikke indeholde brugernavn eller adgangskode")
    return normalized


def effective_implementation_ai_config(
    database: Any,
    organization_id: str,
) -> dict[str, Any]:
    """Return effective config, including the secret for trusted server callers only."""
    organization_id = str(organization_id or "").strip()
    if not organization_id:
        raise ValueError("organization_id is required")

    store = RuntimeSettingsStore(database)
    row = store.get(organization_id, IMPLEMENTATION_AI_SETTING_KEY)
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    env_model = os.getenv("DOR_IMPLEMENTATION_MODEL", "").strip()
    env_base_raw = os.getenv("DOR_IMPLEMENTATION_OPENAI_BASE_URL", "").strip()
    env_base = normalize_openai_base_url(
        env_base_raw or DEFAULT_OPENAI_BASE_URL
    )

    if row is None:
        return {
            "organization_id": organization_id,
            "provider": "openai-compatible",
            "model": env_model,
            "base_url": env_base,
            "api_key": env_key or None,
            "api_key_configured": bool(env_key),
            "source": "environment" if (env_key or env_model or env_base_raw) else "none",
            "updated_by": None,
            "updated_at": None,
        }

    value = row["value"]
    base_url = normalize_openai_base_url(
        str(value.get("base_url") or env_base or DEFAULT_OPENAI_BASE_URL)
    )
    model = str(value.get("model") or env_model or "").strip()
    try:
        stored_key = store.secret(organization_id, IMPLEMENTATION_AI_SETTING_KEY)
    except (SettingsEncryptionUnavailable, SettingsSecretUnreadable):
        raise

    api_key = stored_key or env_key or None
    return {
        "organization_id": organization_id,
        "provider": "openai-compatible",
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "api_key_configured": bool(api_key),
        "source": "database",
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


def public_implementation_ai_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return browser-safe state without ever echoing the stored credential."""
    return {
        "organization_id": str(config.get("organization_id") or ""),
        "provider": "openai-compatible",
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or DEFAULT_OPENAI_BASE_URL),
        "api_key_configured": bool(config.get("api_key_configured")),
        "source": str(config.get("source") or "none"),
        "active_for_new_tasks": bool(
            config.get("model") and config.get("api_key_configured")
        ),
        "applies_to": "new_implementation_tasks",
        "updated_by": config.get("updated_by"),
        "updated_at": config.get("updated_at"),
    }


def save_implementation_ai_config(
    database: Any,
    organization_id: str,
    *,
    model: str,
    base_url: str,
    updated_by: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Persist desired config; workers resolve this store before each new AI task."""
    organization_id = str(organization_id or "").strip()
    model = str(model or "").strip()
    if not organization_id:
        raise ValueError("organization_id is required")
    if not model:
        raise ValueError("model is required")
    normalized_base = normalize_openai_base_url(base_url)
    RuntimeSettingsStore(database).put(
        organization_id,
        IMPLEMENTATION_AI_SETTING_KEY,
        {"model": model, "base_url": normalized_base},
        updated_by=updated_by,
        secret=api_key,
        keep_existing_secret=True,
    )
    return effective_implementation_ai_config(database, organization_id)


def probe_implementation_ai(
    config: Mapping[str, Any],
    *,
    timeout_seconds: float = 10.0,
    opener: OpenURL | None = None,
) -> dict[str, Any]:
    """Check credentials and model availability without issuing a generation call."""
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip()
    base_url = normalize_openai_base_url(
        str(config.get("base_url") or DEFAULT_OPENAI_BASE_URL)
    )
    if not api_key or not model:
        return {
            "configured": False,
            "reachable": False,
            "authenticated": False,
            "model_available": False,
            "error": "not_configured",
        }

    request = urllib.request.Request(
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "dor-settings/1.0",
        },
        method="GET",
    )
    call = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))  # nosec B310 - URL is admin-configured and validated.
    try:
        with call(request, timeout_seconds) as response:
            raw = response.read(_MAX_PROBE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            error = "authentication_failed"
        elif exc.code == 404:
            error = "models_endpoint_not_supported"
        else:
            error = "upstream_error"
        return {
            "configured": True,
            "reachable": True,
            "authenticated": False,
            "model_available": False,
            "error": error,
        }
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return {
            "configured": True,
            "reachable": False,
            "authenticated": False,
            "model_available": False,
            "error": "connection_error",
        }

    if len(raw) > _MAX_PROBE_BYTES:
        return {
            "configured": True,
            "reachable": True,
            "authenticated": True,
            "model_available": False,
            "error": "response_too_large",
        }
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "configured": True,
            "reachable": True,
            "authenticated": True,
            "model_available": False,
            "error": "invalid_response",
        }

    data = payload.get("data") if isinstance(payload, Mapping) else None
    model_ids = {
        str(item.get("id"))
        for item in data or []
        if isinstance(item, Mapping) and item.get("id")
    }
    available = model in model_ids
    return {
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "model_available": available,
        "error": None if available else "model_not_found",
    }
