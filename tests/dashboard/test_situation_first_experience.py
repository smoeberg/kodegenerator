from pathlib import Path


APP = Path("dashboard/operator_center.py")
VIEWS = Path("dashboard/case_shell_views.py")
SETTINGS = Path("dashboard/settings_view.py")


def test_overview_is_situation_first_not_system_dashboard_first():
    source = VIEWS.read_text(encoding="utf-8")

    assert "Hvad vil du gøre?" in source
    assert "DET VIGTIGSTE NU" in source
    assert "HVAD VIL DU GØRE?" in source
    assert "Opret en sag" in source
    assert "Se mit arbejde" in source
    assert "Find en sag" in source
    assert "Systemoplysninger" in source

    # Execution/readiness problems stay available as secondary system context.
    assert '_render_system_details(client, execution_error)' in source
    assert "SYSTEMHELDBRED" not in source
    assert "Execution-data er midlertidigt utilgængelige.</b>" not in source


def test_case_view_leads_with_action_situation_and_activity():
    source = VIEWS.read_text(encoding="utf-8")

    assert "NÆSTE HANDLING" in source
    assert "SITUATION" in source
    assert "AKTUEL AKTIVITET" in source
    assert "PROCES" in source
    assert "EVIDENS" in source
    assert "Hvorfor dette er næste skridt" in source
    assert "Bolden er hos:" in source

    assert source.index("NÆSTE HANDLING") < source.index("PROCES")
    assert source.index("SITUATION") < source.index("PROCES")
    assert source.index("AKTUEL AKTIVITET") < source.index("PROCES")


def test_case_actions_still_delegate_to_backend_authority():
    source = VIEWS.read_text(encoding="utf-8")

    assert "should_render_gate_actions(item)" in source
    assert "render_gate_actions(client, item)" in source
    assert "render_project_lifecycle_tools(client, item)" in source
    assert "transition_workflow(" not in source
    assert "advance_pipeline(" not in source


def test_operator_shell_keeps_case_first_navigation_and_unified_settings():
    source = APP.read_text(encoding="utf-8")

    assert 'WORK_NAV = ("Overblik", "Mit arbejde", "Sager", "Søg")' in source
    assert 'ADMIN_NAV = ("Ingen", "Indstillinger")' in source
    assert "situation-first" in source
    assert "render_settings(client)" in source


def test_settings_rejects_terminal_first_ordinary_configuration():
    source = SETTINGS.read_text(encoding="utf-8")
    assert "uden terminal eller serverfiler" in source
    assert "Brugere" in source
    assert "Integrationer" in source
    assert "System" in source
