from __future__ import annotations

from api.auth import get_current_active_user
from api.endpoints import integrations
from api.main import app


def _flatten_routes(routes):
    """Recursively extract nested routes from FastAPI routers (v0.141+)."""
    flat = []
    for route in routes:
        if hasattr(route, "routes"):
            flat.extend(_flatten_routes(route.routes))
        elif hasattr(route, "original_router") and hasattr(route.original_router, "routes"):
            flat.extend(_flatten_routes(route.original_router.routes))
        else:
            flat.append(route)
    return flat


def test_integrations_router_exposes_redmine_health_contract() -> None:
    routes = {
        (route.path, frozenset(getattr(route, "methods", ()) or ()))
        for route in integrations.router.routes
    }
    assert ("/api/v1/integrations/redmine/health", frozenset({"GET"})) in routes


def test_redmine_health_is_mounted_with_authenticated_dependency() -> None:
    # Route is mounted (FastAPI 0.141+ wraps included routers).
    mounted = any(
        getattr(r, "path", None) == "/api/v1/integrations/redmine/health"
        for r in _flatten_routes(app.routes)
    )
    assert mounted
    # Include-time auth dependency lives on include_context.dependencies.
    dep_calls = set()
    for r in app.routes:
        ctx = getattr(r, "include_context", None)
        ctx_deps = getattr(ctx, "dependencies", None) or ()
        for dep in ctx_deps:
            dep_calls.add(dep.dependency)
    assert get_current_active_user in dep_calls


def test_redmine_health_endpoint_returns_sanitized_service_result(monkeypatch) -> None:
    expected = {
        "integration": "redmine",
        "configured": True,
        "reachable": True,
        "verified": True,
        "checked_at": "2026-09-04T19:00:00Z",
        "error": None,
        "missing_configuration": [],
    }
    monkeypatch.setattr(integrations, "check_redmine_health", lambda: expected)

    assert integrations.redmine_health() == expected
