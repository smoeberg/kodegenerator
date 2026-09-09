from pathlib import Path


APP = Path("dashboard/operator_center.py")
ACTIONS = Path("dashboard/case_shell_actions.py")
VIEWS = Path("dashboard/case_shell_views.py")
WORKBENCH = Path("dashboard/case_workbench.py")
PROJECT_LIFECYCLE = Path("dashboard/project_lifecycle.py")
SETTINGS = Path("dashboard/settings_view.py")
COMPOSE = Path("compose.yml")
CONFIG = Path(".streamlit/config.toml")


def test_operator_center_is_canonical_dashboard_entrypoint():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "dashboard/operator_center.py" in compose


def test_operator_center_hides_legacy_streamlit_multipage_chrome():
    config = CONFIG.read_text(encoding="utf-8")
    assert "showSidebarNavigation = false" in config


def test_operator_center_uses_authenticated_api_client_only():
    source = APP.read_text(encoding="utf-8")
    assert "from dashboard.api_client import DORAPIClient, DORAPIError" in source
    assert "requests." not in source
    assert "urlopen" not in source
    assert "sqlite" not in source.lower()
    assert "psycopg" not in source.lower()


def test_case_shell_preserves_canonical_project_authority():
    app_source = APP.read_text(encoding="utf-8")
    actions_source = ACTIONS.read_text(encoding="utf-8")
    lifecycle_source = PROJECT_LIFECYCLE.read_text(encoding="utf-8")

    assert "/api/v1/control-plane/projects" in app_source
    assert "render_project_lifecycle_console" in actions_source
    assert "/launch" in lifecycle_source
    assert "expected_project_fingerprint" in lifecycle_source


def test_case_shell_uses_backend_gate_authority():
    source = ACTIONS.read_text(encoding="utf-8")
    assert "/api/v1/execution/" in source
    assert "/gates/decide" in source
    assert "/gates/retry" in source
    assert "/gates/rework" in source
    assert 'gate["can_retry"]' in source
    assert 'gate["can_rework"]' in source


def test_operator_center_has_no_local_workflow_transition_engine():
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (APP, ACTIONS, VIEWS, WORKBENCH)
    )
    assert "transition_workflow(" not in source
    assert "advance_pipeline(" not in source


def test_case_views_keep_time_aware_danish_greeting():
    source = VIEWS.read_text(encoding="utf-8")
    assert "Europe/Copenhagen" in source
    assert 'return "Godmorgen"' in source
    assert 'return "Goddag"' in source
    assert 'return "Godaften"' in source
    assert "greeting()" in source


def test_operator_center_builds_shared_case_workbench():
    source = APP.read_text(encoding="utf-8")
    assert "from dashboard.case_workbench import build_case_workbench" in source
    assert "snapshot = build_case_workbench(projects, executions)" in source
    assert "overview(client, snapshot, execution_error)" in source
    assert "work_view(snapshot)" in source
    assert "cases_view(client, snapshot)" in source
    assert "search_view(client, snapshot)" in source


def test_operator_center_has_case_first_navigation_and_one_settings_entry():
    source = APP.read_text(encoding="utf-8")
    assert 'WORK_NAV = ("Overblik", "Mit arbejde", "Sager", "Søg")' in source
    assert 'ADMIN_NAV = ("Ingen", "Indstillinger")' in source
    assert "render_settings(client)" in source
    assert 'ADMIN_NAV = ("Ingen", "Governance", "Integration")' not in source


def test_settings_unifies_ordinary_administration_surfaces():
    source = SETTINGS.read_text(encoding="utf-8")
    for label in ("Organisation", "Brugere", "Integrationer", "System", "AI & Governance"):
        assert label in source
    assert "render_redmine_integration(client)" in source
    assert "render_multi_bot_control_plane(client, organization_id)" in source


def test_legacy_capabilities_are_contextual_not_top_level():
    source = VIEWS.read_text(encoding="utf-8")
    assert "render_gate_actions(client, item)" in source
    assert "render_execution_detail(client, technical_workflow_id)" in source
    assert "evidence_lookup(client)" in source
    assert "render_project_lifecycle_tools(client, item)" in source
