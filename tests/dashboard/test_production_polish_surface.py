from pathlib import Path


def test_operator_overview_uses_shared_status_and_timestamp_primitives() -> None:
    source = Path("dashboard/operator_overview.py").read_text(encoding="utf-8")

    assert "from dashboard.ui_primitives import format_timestamp, status_badge" in source
    assert 'with st.spinner("Henter execution-overblik…")' in source
    assert "format_timestamp(item['updated_at'])" in source
    assert "status_badge(item['current_state'])" in source
    assert "status_badge(blocker.get('decision') or 'pending', blocking=True)" in source


def test_canonical_app_hides_technical_payloads_and_warns_sensitive_actions() -> None:
    source = Path("dashboard/app.py").read_text(encoding="utf-8")

    assert "from dashboard.ui_primitives import count_label, format_timestamp, status_badge" in source
    assert 'with st.expander("Tekniske projektdata")' in source
    assert 'with st.expander("Teknisk launch-resultat")' in source
    assert 'with st.expander("Tekniske readiness-data")' in source
    assert "Jeg har verificeret projektet og bekræfter launch-operationen" in source
    assert "Rework køer nyt upstream arbejde" in source
    assert "Retry åbner en ny human decision-round" in source
    assert "Afvisning registrerer en fail-closed governance-beslutning" in source
    assert "format_timestamp(proposal['created_at'])" in source


def test_production_polish_does_not_add_api_authority() -> None:
    source = Path("dashboard/app.py").read_text(encoding="utf-8")
    primitives = Path("dashboard/ui_primitives.py").read_text(encoding="utf-8")

    assert "APIRouter" not in source
    assert "APIRouter" not in primitives
    assert "client.post(" not in primitives
    assert "session_state" not in primitives
