"""Human-facing Redmine configuration inside DOR Settings."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.integration_view_model import normalize_redmine_health


def _friendly_error(exc: DORAPIError) -> str:
    if exc.status_code == 403:
        return "Du har ikke administratorrettigheder til denne organisations integrationer."
    if exc.status_code == 422:
        return "En eller flere værdier er ugyldige. Kontrollér URL og projekt-ID."
    if exc.status_code == 503:
        return "DOR kan ikke beskytte den hemmelige nøgle lige nu. Kontrollér systemets krypteringsopsætning."
    return f"Indstillingen kunne ikke gemmes lige nu (fejlkode {exc.status_code})."


def _show_test_result(payload: Any) -> None:
    status = normalize_redmine_health(payload)
    if status["level"] == "success":
        st.success("Forbindelsen virker, og DOR kan læse det valgte Redmine-projekt.")
    elif status["error"] == "authentication_failed":
        st.error("Redmine afviste API-nøglen. Kontrollér nøglen og prøv igen.")
    elif status["error"] == "project_not_found":
        st.error("Redmine kunne nås, men projektet blev ikke fundet. Kontrollér projekt-ID'et.")
    elif status["error"] == "timeout":
        st.error("Redmine svarede ikke i tide. Kontrollér URL, netværk og Redmine-status.")
    elif status["error"] == "connection_error":
        st.error("DOR kunne ikke oprette forbindelse til Redmine. Kontrollér URL og netværk.")
    elif status["error"] in {"not_configured", "invalid_configuration"}:
        st.warning("Redmine er ikke konfigureret færdigt endnu.")
    else:
        st.error("Redmine svarede, men forbindelsen kunne ikke verificeres.")


def render_redmine_integration(client: DORAPIClient) -> None:
    """Configure, save and test Redmine without exposing the stored API key."""
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    st.markdown("### Redmine")
    st.caption(
        "Opsæt forbindelsen her. API-nøglen gemmes krypteret af backend og vises aldrig igen."
    )
    if not organization_id:
        st.info("Vælg først en organisation.")
        return

    try:
        config = client.get(
            "/api/v1/integrations/redmine/config",
            params={"organization_id": organization_id},
        )
    except DORAPIError as exc:
        st.error(_friendly_error(exc))
        return
    if not isinstance(config, Mapping):
        config = {}

    source = str(config.get("source") or "none")
    if source == "environment":
        st.info(
            "Der findes en ældre serverkonfiguration. Gem formularen nedenfor for at flytte den ind i DORs indstillinger."
        )

    with st.form(f"redmine-settings-{organization_id}"):
        url = st.text_input(
            "Redmine-adresse",
            value=str(config.get("url") or ""),
            placeholder="https://redmine.example.dk",
            help="Adressen til Redmine. DOR tilføjer selv den nødvendige API-sti.",
        )
        project_id = st.text_input(
            "Projekt-ID",
            value=str(config.get("project_id") or ""),
            help="Redmines projekt-identifikator, fx dor-platform.",
        )
        key_label = (
            "Ny API-nøgle (lad feltet være tomt for at beholde den gemte)"
            if config.get("api_key_configured")
            else "API-nøgle"
        )
        api_key = st.text_input(key_label, type="password")
        saved = st.form_submit_button("Gem Redmine-indstillinger", type="primary")

    if saved:
        payload: dict[str, Any] = {
            "organization_id": organization_id,
            "url": url.strip(),
            "project_id": project_id.strip(),
        }
        if api_key.strip():
            payload["api_key"] = api_key.strip()
        try:
            client.put("/api/v1/integrations/redmine/config", json=payload)
        except DORAPIError as exc:
            st.error(_friendly_error(exc))
        else:
            st.success("Redmine-indstillingerne er gemt sikkert.")
            st.rerun()

    cols = st.columns([1, 2])
    with cols[0]:
        test = st.button("Test forbindelse", use_container_width=True)
    with cols[1]:
        if config.get("api_key_configured"):
            st.caption("API-nøgle: gemt sikkert · vises ikke i browseren")
        else:
            st.caption("API-nøgle: mangler")

    if test:
        try:
            result = client.post(
                "/api/v1/integrations/redmine/test",
                params={"organization_id": organization_id},
            )
        except DORAPIError as exc:
            st.error(_friendly_error(exc))
        else:
            _show_test_result(result)
