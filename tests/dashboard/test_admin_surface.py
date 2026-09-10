from pathlib import Path

from dashboard.admin_api import CAPABILITIES


def test_admin_has_dedicated_entrypoint_and_reuses_shared_transport() -> None:
    source = Path("dashboard/admin_app.py").read_text(encoding="utf-8")

    assert "from dashboard.api_client import DORAPIClient, DORAPIError" in source
    assert "from dashboard.state import authenticated, clear_auth, init_state" in source
    assert "DOR_API_TOKEN" not in source
    assert "DOR_API_BASE" not in source
    assert "requests." not in source
    assert "urlopen" not in source


def test_admin_surface_contains_no_direct_execution_authority() -> None:
    source = Path("dashboard/admin_app.py").read_text(encoding="utf-8")
    facade = Path("dashboard/admin_api.py").read_text(encoding="utf-8")
    combined = source + facade

    forbidden_calls = (
        ".deploy(",
        ".release(",
        ".execute(",
        "create_pr(",
        "apply_patch(",
        "run_worker(",
        "run_workflow(",
    )
    for call in forbidden_calls:
        assert call not in combined


def test_admin_does_not_persist_secret_values_in_explicit_session_state() -> None:
    source = Path("dashboard/admin_app.py").read_text(encoding="utf-8")

    assert 'session_state["api_key"]' not in source
    assert 'session_state["password"]' not in source
    assert 'session_state["token"]' not in source
    assert "Eksisterende credential" in source
    assert "type=\"password\"" in source


def test_missing_admin_contracts_are_explicitly_fail_closed() -> None:
    support = {item.key: item.support for item in CAPABILITIES}
    source = Path("dashboard/admin_app.py").read_text(encoding="utf-8")

    assert support["audit"] == "unsupported"
    assert support["repository_mapping"] == "unsupported"
    assert "fabrikerer derfor ikke audit records" in source
    assert "Status kan ikke fastslås" in source


def test_gui03_does_not_import_operator_case_journey() -> None:
    source = Path("dashboard/admin_app.py").read_text(encoding="utf-8")

    assert "case_shell" not in source
    assert "case_workbench" not in source
    assert "implementation_apply" not in source
    assert "WorkflowRealtime" not in source
