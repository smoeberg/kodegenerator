"""Streamlit page for explicit human review and governed patch application."""
from __future__ import annotations

from typing import Mapping

import streamlit as st

from dashboard.implementation_apply import render_implementation_apply
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Patch Review & Apply",
    page_icon="🛡️",
    layout="wide",
)
init_state()

st.title("🛡️ Patch Review & Apply")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før governed patch apply.")
    st.stop()

render_implementation_apply()

apply_result = st.session_state.get("implementation_apply_result")
if isinstance(apply_result, Mapping) and apply_result.get("applied") is True:
    st.page_link(
        "pages/06_Delivery_Verification_Handoff.py",
        label="Fortsæt til Delivery Verification Handoff",
        icon="📦",
    )
