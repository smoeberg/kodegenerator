"""Integration boundary checks for the canonical runtime API."""

import importlib
import importlib.util

import pytest

from api.api_surface import (
    CANONICAL_AUTHENTICATED_MODULES,
    RETIRED_LEGACY_MODULES,
    RETIRED_LEGACY_PATH_PREFIXES,
    validate_canonical_modules,
)


def test_api_main_imports_with_canonical_runtime(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    module = importlib.import_module("api.main")
    from api.endpoints import control_plane, implementation_agent, workflows

    assert module.app.title == "Digital Organization Runtime (DOR)"
    routes = [
        route for route in module.app.routes if getattr(route, "path", None) is not None
    ]
    assert any(route.path == "/health" for route in routes)
    workflow_routes = [
        route
        for route in workflows.router.routes
        if getattr(route, "path", None) is not None
    ]
    assert any(
        route.path == "/workflows/{workflow_id}/transition" for route in workflow_routes
    )
    implementation_routes = [
        route
        for route in implementation_agent.router.routes
        if getattr(route, "path", None) is not None
    ]
    assert any(
        route.path == "/implementation-agent/proposals"
        for route in implementation_routes
    )
    control_plane_routes = [
        route
        for route in control_plane.router.routes
        if getattr(route, "path", None) is not None
    ]
    assert any(
        route.path == "/api/v1/control-plane/projects" for route in control_plane_routes
    )
    assert any(
        route.path == "/api/v1/control-plane/projects/{project_id}/launch"
        for route in control_plane_routes
    )


def test_api_main_exposes_no_legacy_dor_runtime_db_modules(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    import sys

    for mod_name in list(sys.modules.keys()):
        if "dor_runtime_db" in mod_name:
            del sys.modules[mod_name]

    import api.main  # noqa: F401

    for mod_name in sys.modules:
        assert "dor_runtime_db" not in mod_name, (
            f"Legacy module {mod_name} imported by API runtime"
        )


def test_api_main_mounts_only_canonical_router_whitelist(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    import api.main

    paths = set(api.main.app.openapi()["paths"])
    assert "/api/v1/control-plane/projects" in paths
    assert "/implementation-agent/proposals" in paths
    assert "/api/v1/swarm/events/{project_id}" in paths
    from api.endpoints import swarm_websocket

    assert any(
        getattr(route, "path", None) == "/api/v1/swarm/ws/{project_id}"
        for route in swarm_websocket.router.routes
    )
    assert "/tasks/" not in paths
    assert "/actors/digital-employee" not in paths
    assert "/organizations/" not in paths
    assert "/api/v1/bot-selections" in paths
    assert len(api.main.CANONICAL_AUTHENTICATED_ROUTERS) == len(
        CANONICAL_AUTHENTICATED_MODULES
    )
    assert "/api/v1/integrations/redmine/health" in paths
    assert "/api/v1/bot-governance/connections" in paths
    assert "/api/v1/bot-evidence/evaluations/{evaluation_id}" in paths
    assert "/api/v1/bot-evidence/integration-receipts/{plan_fingerprint}" in paths
    # Pipeline gate approval endpoints are deliberately part of the canonical set.
    assert "/api/v1/pipeline-gates/approve" in paths
    # Development/execution cockpit is a canonical authenticated router as well.
    assert "/api/v1/execution/{workflow_id}" in paths


def test_retired_legacy_router_modules_do_not_exist() -> None:
    for module_name in RETIRED_LEGACY_MODULES:
        assert importlib.util.find_spec(module_name) is None


def test_retired_legacy_paths_are_not_mounted(monkeypatch) -> None:
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    import api.main

    paths = set(api.main.app.openapi()["paths"])
    assert not {path for path in paths if path.startswith(RETIRED_LEGACY_PATH_PREFIXES)}


def test_router_inventory_fails_closed_on_unexpected_module() -> None:
    with pytest.raises(RuntimeError, match="unexpected"):
        validate_canonical_modules(
            (*CANONICAL_AUTHENTICATED_MODULES, "api.endpoints.tasks")
        )
