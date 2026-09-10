from pathlib import Path

from dashboard.admin_api import CAPABILITIES
from dashboard.settings_view import classify_health_status

OPERATOR = Path("dashboard/operator_center.py")
SETTINGS = Path("dashboard/settings_view.py")
REDMINE = Path("dashboard/redmine_integration.py")
ADMIN_ACCESS = Path("dashboard/admin_access.py")
ADMIN_APP = Path("dashboard/admin_app.py")
COMPOSE = Path("compose.yml")
README = Path("dashboard/README.md")


def test_administration_is_integrated_into_canonical_operator_entrypoint() -> None:
    source = OPERATOR.read_text(encoding="utf-8")
    assert "from dashboard.admin_access import fetch_organization_admin_status" in source
    assert 'ADMIN_NAV = ("Ingen", "Administration")' in source
    assert "render_settings(client)" in source
    assert "admin_status is True" in source
    assert not ADMIN_APP.exists()


def test_non_admin_or_unknown_client_state_cannot_preserve_admin_navigation() -> None:
    source = OPERATOR.read_text(encoding="utf-8")
    assert 'st.session_state["operator_admin_nav"] = "Ingen"' in source
    assert "if admin_status is not True:" in source
    assert "Status kan ikke fastslås" in source


def test_integrated_admin_surface_contains_no_direct_execution_authority() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (OPERATOR, SETTINGS, REDMINE, ADMIN_ACCESS))
    for call in (".deploy(", ".release(", ".execute(", "create_pr(", "apply_patch(", "run_worker(", "run_workflow("):
        assert call not in combined
    assert "sqlite" not in SETTINGS.read_text(encoding="utf-8").lower()
    assert "psycopg" not in SETTINGS.read_text(encoding="utf-8").lower()


def test_admin_secrets_are_masked_and_empty_replacements_are_omitted() -> None:
    combined = SETTINGS.read_text(encoding="utf-8") + REDMINE.read_text(encoding="utf-8")
    assert 'type="password"' in combined
    assert 'if api_key.strip():' in combined
    assert 'body["api_key"] = api_key.strip()' in combined
    assert 'session_state["api_key"]' not in combined
    assert 'session_state["password"]' not in combined
    assert "vises aldrig igen" in combined


def test_projects_remain_read_only_and_missing_contracts_remain_explicit() -> None:
    support = {item.key: item.support for item in CAPABILITIES}
    settings = SETTINGS.read_text(encoding="utf-8")
    assert support["projects"] == "read-only"
    assert support["roles"] == "limited"
    assert support["repository_mapping"] == "unsupported"
    assert "Project membership, departments og repository mappings" in settings
    assert "create_project" not in settings


def test_health_classification_never_maps_unknown_to_healthy() -> None:
    assert classify_health_status({"status": "ok"}, expected="ok") == "healthy"
    assert classify_health_status({"status": "ready"}, expected="ready") == "healthy"
    assert classify_health_status({"status": "error"}, expected="ready") == "unhealthy"
    assert classify_health_status({"status": "unhealthy"}, expected="ok") == "unhealthy"
    assert classify_health_status({}, expected="ready") == "unknown"
    assert classify_health_status({"status": "mystery"}, expected="ready") == "unknown"
    assert classify_health_status("ready", expected="ready") == "unknown"


def test_deployment_has_one_internal_operator_gui_on_8501_and_no_8503() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "dashboard/operator_center.py" in compose
    assert "--server.port=8501" in compose
    assert "${DOR_DASHBOARD_PORT:-8501}:8501" in compose
    assert "8503" not in compose
    assert "admin_app.py" not in compose


def test_documentation_marks_standalone_gui03_as_retired() -> None:
    source = README.read_text(encoding="utf-8")
    assert "GUI-01  Operator + Administration  :8501" in source
    assert "GUI-02  Customer Portal            :8502" in source
    assert "Der findes ingen GUI-03 deployment på `8503`." in source
    assert "tidligere standalone entrypoint `dashboard/admin_app.py` er fjernet" in source
