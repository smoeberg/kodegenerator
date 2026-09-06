"""Streamlit page for immutable requirement-to-artifact traceability."""

from __future__ import annotations

from typing import Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient
from dashboard.requirements_traceability import render_requirement_traceability
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Requirement Traceability",
    page_icon="🔗",
    layout="wide",
)
init_state()

st.title("🔗 Requirement → Artifact Traceability")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før requirement traceability.")
    st.stop()

render_requirement_traceability(
    DORAPIClient(token=st.session_state.get("access_token"))
)

result = st.session_state.get("requirement_traceability_result")
if isinstance(result, Mapping):
    manifest = result.get("manifest")
    if isinstance(manifest, Mapping) and manifest.get("status") == "complete":
        st.page_link(
            "pages/09_Multi_Spec_Artifact_Acceptance.py",
            label="Fortsæt til Multi-Spec Artifact Acceptance",
            icon="🧩",
        )
