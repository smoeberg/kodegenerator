from pathlib import Path


RETIRED_DASHBOARD_PATHS = (
    "dashboard/decision_cockpit.py",
    "dashboard/swarm_monitor.py",
    "dashboard/workflow_cockpit.py",
    "dashboard/fixtures.py",
    "dashboard/index.html",
    "dashboard/control_plane_api.py",
    "dashboard/catalog.py",
    "dashboard/security.py",
    "dashboard/pages/00_Project_Lifecycle.py",
)


def test_retired_dashboard_surfaces_do_not_exist():
    for path in RETIRED_DASHBOARD_PATHS:
        assert not Path(path).exists(), f"retired dashboard surface restored: {path}"


def test_project_lifecycle_capability_remains_available_in_case_shell():
    case_actions = Path("dashboard/case_shell_actions.py").read_text(encoding="utf-8")

    assert "from dashboard.project_lifecycle import render_project_lifecycle_console" in case_actions
    assert "render_project_lifecycle_console(client, organization_id, item.project)" in case_actions
    assert "Vis avancerede lifecycle-handlinger" in case_actions


def test_canonical_app_uses_one_authenticated_transport():
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")
    governance_source = Path("dashboard/multi_bot_control_plane.py").read_text(
        encoding="utf-8"
    )

    assert "render_multi_bot_control_plane" in app_source
    assert "from dashboard.api_client import DORAPIClient" in governance_source
    assert "DOR_API_TOKEN" not in governance_source
    assert "DOR_API_BASE" not in governance_source
    assert "urlopen" not in governance_source
