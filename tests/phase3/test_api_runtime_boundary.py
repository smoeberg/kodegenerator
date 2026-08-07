"""Integration boundary checks for the canonical runtime API."""

import importlib
from pathlib import Path


def test_api_main_imports_with_canonical_runtime(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "phase3-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "phase3-test-password")

    module = importlib.import_module("api.main")

    assert module.app.title == "Digital Organization Runtime (DOR)"
    assert any(route.path == "/health" for route in module.app.routes)
    assert any(route.path == "/workflows/{workflow_id}/transition" for route in module.app.routes)


def test_mounted_api_has_no_legacy_persistence_adapter_reference():
    main_source = Path("api/main.py").read_text(encoding="utf-8")
    workflow_source = Path("api/endpoints/workflows.py").read_text(encoding="utf-8")

    assert "DORDBAdapter" not in main_source
    assert "DORRuntimeDB" not in main_source
    assert "db_adapter" not in workflow_source
