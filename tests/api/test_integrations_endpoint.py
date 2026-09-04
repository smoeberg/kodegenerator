from __future__ import annotations

from api.endpoints import integrations


def test_integrations_router_exposes_redmine_health_contract() -> None:
    routes = {
        (route.path, frozenset(getattr(route, "methods", ()) or ()))
        for route in integrations.router.routes
    }
    assert ("/api/v1/integrations/redmine/health", frozenset({"GET"})) in routes


def test_redmine_health_endpoint_returns_sanitized_service_result(monkeypatch) -> None:
    expected = {
        "integration": "redmine",
        "configured": True,
        "reachable": True,
        "verified": True,
        "base_url": "https://redmine.example.test",
        "project_id": "project-a",
        "checked_at": "2026-09-04T19:00:00Z",
        "error": None,
        "missing_configuration": [],
    }
    monkeypatch.setattr(integrations, "check_redmine_health", lambda: expected)

    assert integrations.redmine_health() == expected
