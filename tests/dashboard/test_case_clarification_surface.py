from pathlib import Path


CLARIFICATION = Path("dashboard/case_clarification.py")
VIEWS = Path("dashboard/case_shell_views.py")


def test_case_workbench_places_clarification_in_normal_case_flow():
    views = VIEWS.read_text(encoding="utf-8")
    assert "from dashboard.case_clarification import render_case_clarification" in views
    assert '<div class="section-label">AFKLARING</div>' in views
    assert "render_case_clarification(client, item)" in views
    assert views.index("NÆSTE HANDLING") < views.index("AFKLARING") < views.index("AKTUEL AKTIVITET")


def test_onboarding_is_bound_to_selected_case_and_hides_provenance_ids():
    source = CLARIFICATION.read_text(encoding="utf-8")
    assert 'project_id = item.projection.case_id' in source
    assert '"command_id": uuid4().hex' in source
    assert '"project_id": project_id' in source
    assert '"supersedes_intent_id"' in source
    assert 'st.text_input("Intent ID"' not in source
    assert 'st.text_input("Command ID"' not in source


def test_decisions_are_project_scoped_and_choices_come_from_backend():
    source = CLARIFICATION.read_text(encoding="utf-8")
    assert '"/api/v1/decisions/pending"' in source
    assert 'params={"project_id": project_id}' in source
    assert 'decision.get("alternatives", [])' in source
    assert 'f"/api/v1/decisions/{decision_id}/resolve"' in source
    assert '"selected_alternative": selected' in source
    assert "create_decision" not in source


def test_clarification_does_not_introduce_client_side_authority_or_shell_paths():
    source = CLARIFICATION.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "subprocess" not in lowered
    assert "os.system" not in lowered
    assert "shell=true" not in lowered
    assert "transition_workflow" not in source
    assert "advance_pipeline" not in source
