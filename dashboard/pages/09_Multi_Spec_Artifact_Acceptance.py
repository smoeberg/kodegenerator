"""Streamlit page for multi-spec verified artifact acceptance."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient
from dashboard.artifact_acceptance import render_artifact_acceptance
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Multi-Spec Artifact Acceptance",
    page_icon="🧩",
    layout="wide",
)
init_state()

st.title("🧩 Multi-Spec Verified Artifact Acceptance")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før artifact acceptance.")
    st.stop()

render_artifact_acceptance(
    DORAPIClient(token=st.session_state.get("access_token"))
)
