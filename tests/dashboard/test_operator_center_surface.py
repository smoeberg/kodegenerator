from pathlib import Path


APP = Path("dashboard/operator_center.py")
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


def test_operator_center_uses_canonical_project_commands():
    source = APP.read_text(encoding="utf-8")
    assert "/api/v1/control-plane/projects" in source
    assert "/launch" in source
    assert "expected_project_fingerprint" in source


def test_operator_center_uses_backend_gate_authority():
    source = APP.read_text(encoding="utf-8")
    assert "/api/v1/execution/" in source
    assert "/gates/decide" in source
    assert "/gates/retry" in source
    assert "/gates/rework" in source
    assert "can_retry" in source
    assert "can_rework" in source


def test_operator_center_has_no_local_workflow_transition_engine():
    source = APP.read_text(encoding="utf-8")
    assert "transition_workflow(" not in source
    assert "current_state =" not in source
    assert "advance_pipeline(" not in source


def test_operator_center_has_time_aware_danish_greeting():
    source = APP.read_text(encoding="utf-8")
    assert "Europe/Copenhagen" in source
    assert 'return "Godmorgen"' in source
    assert 'return "Goddag"' in source
    assert 'return "Godaften"' in source
    assert "_greeting()" in source


def test_operator_center_has_required_surfaces():
    source = APP.read_text(encoding="utf-8")
    for label in ("Overblik", "Beslutninger", "Projekter", "Execution", "Evidens", "Governance", "Integration"):
        assert label in source
