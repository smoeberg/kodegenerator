from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_operator_overview_mounts_lifecycle_for_active_workflow() -> None:
    source = (ROOT / "dashboard" / "operator_overview.py").read_text()

    assert "from dashboard.cockpit_lifecycle import render_cockpit_lifecycle" in source
    assert 'st.session_state.get("workflow_input")' in source
    assert 'st.session_state.get("selected_workflow_id")' in source
    assert "render_cockpit_lifecycle(client, active_workflow_id)" in source


def test_lifecycle_surface_states_backend_authority() -> None:
    source = (ROOT / "dashboard" / "cockpit_lifecycle.py").read_text()

    assert "Decision Cockpit lifecycle" in source
    assert "Operatorfokus" in source
    assert "Execution API er fortsat eneste" in source
    assert "Backend afgør fortsat, om Advance accepteres." in source
