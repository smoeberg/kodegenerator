import importlib


def test_execution_rework_endpoint_is_mounted(monkeypatch) -> None:
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "rework-surface-test-secret")
    monkeypatch.setenv("DOR_ADMIN_PASSWORD", "rework-surface-test-password")

    api_main = importlib.import_module("api.main")
    paths = set(api_main.app.openapi()["paths"])

    assert "/api/v1/execution/{workflow_id}/gates/rework" in paths
