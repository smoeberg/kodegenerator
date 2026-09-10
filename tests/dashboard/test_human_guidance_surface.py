from pathlib import Path


APP = Path("dashboard/operator_center.py")
ACTIONS = Path("dashboard/case_shell_actions.py")
FEEDBACK = Path("dashboard/user_feedback.py")


def test_work_surfaces_have_guided_no_organization_state() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "_render_no_organization_state" in source
    assert "Vælg eller opret en organisation" in source
    assert "Gå til Indstillinger" in source
    assert "nav in WORK_NAV and not organization_id" in source


def test_primary_case_actions_use_human_error_guidance() -> None:
    source = ACTIONS.read_text(encoding="utf-8")

    assert "render_api_error" in source
    assert "API-fejl (" not in source
    assert "Rework afvist (" not in source
    assert "Retry afvist (" not in source
    assert "DOR arbejder nu på de ønskede ændringer." in source


def test_error_feedback_keeps_raw_detail_behind_disclosure() -> None:
    source = FEEDBACK.read_text(encoding="utf-8")

    assert 'with st.expander("Tekniske detaljer")' in source
    assert 'st.code(str(exc))' in source
    assert "clear_auth()" in source
    assert 'st.button("Hent aktuel version"' in source


def test_gui_does_not_retry_mutations_automatically() -> None:
    source = FEEDBACK.read_text(encoding="utf-8")

    assert "client.post(" not in source
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
