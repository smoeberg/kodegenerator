"""Server-side Redmine connectivity verification.

Secrets stay inside the API process.  The public health result deliberately
contains only bounded status categories and sanitized configuration metadata;
upstream response bodies and API keys are never returned.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import requests

_DEFAULT_CONNECT_TIMEOUT = 3.05
_DEFAULT_READ_TIMEOUT = 5.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_base_url(value: str) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )


def check_redmine_health(
    *,
    session: requests.Session | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Verify configured Redmine credentials against the configured project.

    Optional arguments exist for deterministic tests; production callers use
    environment configuration.  A result is verified only after a successful
    authenticated project response with a valid Redmine project object.
    """
    raw_url = base_url if base_url is not None else os.getenv("REDMINE_URL", "")
    raw_key = api_key if api_key is not None else os.getenv("REDMINE_API_KEY", "")
    raw_project = (
        project_id if project_id is not None else os.getenv("REDMINE_PROJECT_ID", "")
    )

    sanitized_url = _sanitize_base_url(raw_url)
    key = str(raw_key or "").strip()
    project = str(raw_project or "").strip()
    missing: list[str] = []
    if not str(raw_url or "").strip():
        missing.append("REDMINE_URL")
    if not key:
        missing.append("REDMINE_API_KEY")
    if not project:
        missing.append("REDMINE_PROJECT_ID")

    base_result: dict[str, Any] = {
        "integration": "redmine",
        "configured": not missing and sanitized_url is not None,
        "reachable": False,
        "verified": False,
        "base_url": sanitized_url,
        "project_id": project or None,
        "checked_at": _utc_now(),
        "error": None,
        "missing_configuration": missing,
    }
    if missing:
        base_result["error"] = "not_configured"
        return base_result
    if sanitized_url is None:
        base_result["error"] = "invalid_configuration"
        return base_result

    client = session or requests.Session()
    endpoint = f"{sanitized_url}/projects/{quote(project, safe='')}.json"
    try:
        response = client.get(
            endpoint,
            headers={
                "Accept": "application/json",
                "X-Redmine-API-Key": key,
            },
            timeout=(_DEFAULT_CONNECT_TIMEOUT, _DEFAULT_READ_TIMEOUT),
            allow_redirects=False,
        )
    except requests.Timeout:
        base_result["error"] = "timeout"
        return base_result
    except requests.RequestException:
        base_result["error"] = "connection_error"
        return base_result

    base_result["reachable"] = True
    if response.status_code in {401, 403}:
        base_result["error"] = "authentication_failed"
        return base_result
    if response.status_code == 404:
        base_result["error"] = "project_not_found"
        return base_result
    if not response.ok:
        base_result["error"] = "upstream_error"
        return base_result

    try:
        payload = response.json()
    except ValueError:
        base_result["error"] = "invalid_response"
        return base_result
    project_payload = payload.get("project") if isinstance(payload, dict) else None
    if not isinstance(project_payload, dict) or not (
        project_payload.get("id") or project_payload.get("identifier")
    ):
        base_result["error"] = "invalid_response"
        return base_result

    base_result["verified"] = True
    return base_result
