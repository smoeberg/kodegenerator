"""Streamlit renderer for server-side Redmine health verification."""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.integration_view_model import normalize_redmine_health


def render_redmine_integration(client: DORAPIClient) -> None:
    st.subheader("Redmine Integration")
    st.caption(
        "Konfigurationen læses kun af API-processen fra REDMINE_URL, "
        "REDMINE_API_KEY og REDMINE_PROJECT_ID. Credentials vises eller sendes "
        "aldrig til browseren."
    )

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

    st.caption(f"Kontrolleret af backend: `{status['checked_at']}`")
    if status["error"]:
        st.caption(f"Backend-status: `{status['error']}`")
