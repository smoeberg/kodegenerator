from pathlib import Path


def test_operator_overview_is_integrated_into_canonical_development_page() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")

    assert "from dashboard.operator_overview import render_operator_overview" in app_source
    assert "render_operator_overview(client)" in app_source
    assert 'st.text_input("Aktivt Workflow ID", key="workflow_input")' in app_source
    assert 'st.session_state["selected_workflow_id"] = workflow_id' in app_source


def test_operator_overview_uses_canonical_execution_summary_endpoint() -> None:
    overview_source = Path("dashboard/operator_overview.py").read_text(encoding="utf-8")

    assert 'client.get("/api/v1/execution")' in overview_source
    assert 'st.session_state["selected_workflow_id"] = item["workflow_id"]' in overview_source
    assert "Åbn i Decision Cockpit" in overview_source
