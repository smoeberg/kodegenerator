"""Human-facing Redmine configuration inside DOR Administration."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.integration_view_model import normalize_redmine_health


def _friendly_error(exc: DORAPIError) -> str:
    if exc.status_code == 401:
        return "Din session er ikke længere gyldig. Log ind igen."
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
        st.error("DOR kunne ikke oprette forbindelse til Redmine.")
    elif status["error"] in {"not_configured", "invalid_configuration"}:
        st.warning("Redmine er ikke konfigureret færdigt endnu.")
    else:
        st.error("Status kan ikke fastslås")


def _render_legacy_health_only(client: DORAPIClient) -> None:
    """Preserve the retired read-only health fallback without mutation authority."""
    st.subheader("Redmine Integration")
    st.caption("Denne ældre visning kan kun kontrollere den serverkonfiguration, der allerede findes.")
    if not st.button("Verificér Redmine-forbindelse", type="primary"):
        st.info("Kør en backend-verifikation for at se den aktuelle integrationsstatus.")
        return
    try:
        payload = client.get("/api/v1/integrations/redmine/health")
    except DORAPIError as exc:
        st.error(f"Redmine health-check fejlede ({exc.status_code}): {exc}")
        return
    status = normalize_redmine_health(payload)
    cols = st.columns(3)
    cols[0].metric("Konfigureret", "Ja" if status["configured"] else "Nej")
    cols[1].metric("Reachable", "Ja" if status["reachable"] else "Nej")
    cols[2].metric("Verificeret", "Ja" if status["verified"] else "Nej")
    if status["level"] == "success":
        st.success(status["message"])
    elif status["level"] == "warning":
        st.warning(status["message"])
    else:
        st.error(status["message"])


def _valid_config(payload: Any, organization_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    config = dict(payload)
    if str(config.get("organization_id") or "").strip() != organization_id:
        return None
    if not isinstance(config.get("api_key_configured"), bool):
        return None
    for key in ("url", "project_id", "source"):
        if key not in config:
            return None
    return config


def render_redmine_integration(client: DORAPIClient) -> None:
    """Configure, save and test Redmine without exposing the stored API key."""
    if not hasattr(client, "put"):
        _render_legacy_health_only(client)
        return
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    st.markdown("### Redmine")
    st.caption("URL, external project ID og credential administreres via backenden. API-nøglen gemmes krypteret og vises aldrig igen.")
    if not organization_id:
        st.warning("Status kan ikke fastslås")
        return
    try:
        payload = client.get("/api/v1/integrations/redmine/config", params={"organization_id": organization_id})
    except DORAPIError as exc:
        st.error(_friendly_error(exc))
        return
    except Exception:
        st.error("Status kan ikke fastslås")
        return
    config = _valid_config(payload, organization_id)
    if config is None:
        st.error("Status kan ikke fastslås")
        return
    if config.get("source") == "environment":
        st.info("Der findes en ældre serverkonfiguration. Gem formularen nedenfor for at flytte den ind i DORs indstillinger.")
    with st.form(f"redmine-settings-{organization_id}"):
        url = st.text_input("Redmine-adresse", value=str(config.get("url") or ""), placeholder="https://redmine.example.dk")
        project_id = st.text_input("Projekt-ID", value=str(config.get("project_id") or ""), help="Redmines eksterne projekt-identifikator.")
        key_label = "Ny API-nøgle (lad feltet være tomt for at beholde den gemte)" if config.get("api_key_configured") else "API-nøgle"
        api_key = st.text_input(key_label, type="password")
        saved = st.form_submit_button("Gem Redmine-indstillinger", type="primary")
    if saved:
        body: dict[str, Any] = {"organization_id": organization_id, "url": url.strip(), "project_id": project_id.strip()}
        if api_key.strip():
            body["api_key"] = api_key.strip()
        try:
            saved_config = client.put("/api/v1/integrations/redmine/config", json=body)
        except DORAPIError as exc:
            st.error(_friendly_error(exc))
        else:
            if _valid_config(saved_config, organization_id) is None:
                st.error("Status kan ikke fastslås")
                return
            st.success("Redmine-indstillingerne er gemt sikkert af backenden.")
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
            result = client.post("/api/v1/integrations/redmine/test", params={"organization_id": organization_id})
        except DORAPIError as exc:
            st.error(_friendly_error(exc))
        except Exception:
            st.error("Status kan ikke fastslås")
        else:
            _show_test_result(result)
