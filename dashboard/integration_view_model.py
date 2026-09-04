"""Pure presentation helpers for external integration health."""
from __future__ import annotations

from typing import Any, Mapping


def normalize_redmine_health(payload: Any) -> dict[str, Any]:
    """Convert the bounded Redmine health contract into fail-closed GUI state."""
    data = payload if isinstance(payload, Mapping) else {}
    configured = data.get("configured") is True
    reachable = data.get("reachable") is True
    backend_verified = data.get("verified") is True
    verified = backend_verified and configured and reachable
    error = str(data.get("error") or "").strip() or None

    missing_value = data.get("missing_configuration")
    missing = (
        [str(item) for item in missing_value if str(item).strip()]
        if isinstance(missing_value, list)
        else []
    )

    if verified:
        status = "verified"
        level = "success"
        message = "Redmine-forbindelsen er verificeret af backend."
    elif not configured:
        status = "not_configured"
        level = "warning"
        suffix = f" Mangler: {', '.join(missing)}." if missing else ""
        message = "Redmine er ikke komplet konfigureret i API-processen." + suffix
    elif not reachable:
        status = "unreachable"
        level = "error"
        if error == "timeout":
            message = "Redmine kunne ikke nås inden for backend-timeout."
        else:
            message = "Redmine kunne ikke nås fra API-processen."
    elif error == "authentication_failed":
        status = "authentication_failed"
        level = "error"
        message = "Redmine svarede, men credentials blev afvist."
    elif error == "project_not_found":
        status = "project_not_found"
        level = "error"
        message = "Redmine svarede, men det konfigurerede projekt blev ikke fundet."
    else:
        status = "unverified"
        level = "error"
        message = "Redmine svarede, men forbindelsen kunne ikke verificeres."

    return {
        "status": status,
        "level": level,
        "message": message,
        "configured": configured,
        "reachable": reachable,
        "verified": verified,
        "base_url": str(data.get("base_url") or "—"),
        "project_id": str(data.get("project_id") or "—"),
        "checked_at": str(data.get("checked_at") or "—"),
        "error": error,
        "missing_configuration": missing,
    }
