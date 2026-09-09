"""Streamlit page for GUI-101 governed project lifecycle controls."""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.project_lifecycle import render_project_lifecycle_console
from dashboard.state import authenticated, init_state

st.set_page_config(page_title="DOR Project Lifecycle", page_icon="🧭", layout="wide")
init_state()

st.title("🧭 Project Lifecycle")
st.caption(
    "GUI projection over canonical Control Plane project state. Backend authorization, "
    "revision checks, active-plan binding and completion evidence remain authoritative."
)

if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før lifecycle-operationer.")
    st.stop()

organization_id = st.session_state.get("organization_id")
if not organization_id:
    st.warning("Vælg en aktiv organisation på DOR Control Plane-forsiden først.")
    st.stop()

client = DORAPIClient(token=st.session_state.get("access_token"))
project_id = st.text_input(
    "Project ID",
    value=st.session_state.get("selected_project_id") or "",
    help="Projektet hentes på ny fra backend før kontrollerne vises.",
).strip()

if not project_id:
    st.info("Vælg et project ID for at hente canonical lifecycle state.")
    st.stop()

try:
    with st.spinner("Henter canonical project snapshot…"):
        project = client.get(
            f"/api/v1/control-plane/projects/{project_id}",
            params={"organization_id": organization_id},
        )
except DORAPIError as exc:
    if exc.status_code == 401:
        st.error("API-sessionen er udløbet. Log ind igen på forsiden.")
    elif exc.status_code == 403:
        st.error("Backend afviste adgang til projektet i den valgte organisation.")
    else:
        st.error(f"Project snapshot kunne ikke hentes ({exc.status_code}): {exc}")
    st.stop()

st.session_state["selected_project_id"] = project_id
st.session_state["selected_project_fingerprint"] = project.get("project_fingerprint")
render_project_lifecycle_console(client, organization_id, project)
