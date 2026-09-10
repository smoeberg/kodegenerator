from pathlib import Path


CLARIFICATION = Path("dashboard/case_clarification.py")
VIEWS = Path("dashboard/case_shell_views.py")


def test_case_workbench_uses_canonical_case_journey_not_clarification_as_primary_ia():
    views = VIEWS.read_text(encoding="utf-8")
    assert "CANONICAL_CASE_JOURNEY" in views
    for label in (
        '"Sag"',
        '"Plan"',
        '"Aktivt arbejdsgrundlag"',
        '"Execution"',
        '"Proposal"',
        '"Beslutning"',
    ):
        assert label in views
    assert '<div class="section-label">AFKLARING</div>' not in views
    assert "render_case_clarification(client, item)" not in views

    plan_call = views.index("render_case_onboarding(client, item)")
    audit_call = views.index("render_case_audit_planning(client, item)")
    execution_call = views.index("render_case_execution_implementation(client, item)")
    provenance_call = views.index("_render_case_proposal_provenance(item)")
    decision_call = views.index("render_case_decisions(client, item)")
    assert plan_call < audit_call < execution_call < provenance_call < decision_call


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
