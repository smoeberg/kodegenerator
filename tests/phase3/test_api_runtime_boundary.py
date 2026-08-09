"""Integration boundary checks for the canonical runtime API."""

import importlib
from pathlib import Path


def test_api_main_imports_with_canonical_runtime(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    module = importlib.import_module("api.main")
    from api.endpoints import implementation_agent, workflows

    assert module.app.title == "Digital Organization Runtime (DOR)"
    routes = [route for route in module.app.routes if getattr(route, "path", None) is not None]
    assert any(route.path == "/health" for route in routes)
    workflow_routes = [route for route in workflows.router.routes if getattr(route, "path", None) is not None]
    assert any(route.path == "/workflows/{workflow_id}/transition" for route in workflow_routes)
    implementation_routes = [
        route
        for route in implementation_agent.router.routes
        if getattr(route, "path", None) is not None
    ]
    assert any(
        route.path == "/implementation-agent/proposals"
        for route in implementation_routes
    )


def test_api_main_exposes_no_legacy_dor_runtime_db_modules(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    import sys
    for mod_name in list(sys.modules.keys()):
        if "dor_runtime_db" in mod_name:
            del sys.modules[mod_name]

    import api.main
    for mod_name in sys.modules.keys():
        assert "dor_runtime_db" not in mod_name, f"Legacy module {mod_name} imported by API runtime"
