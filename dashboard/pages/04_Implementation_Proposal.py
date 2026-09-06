"""Streamlit page for governed Implementation Agent patch proposals."""
from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from dashboard.implementation_proposal import render_implementation_proposal
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Implementation Proposal",
    page_icon="🧩",
    layout="wide",
)
init_state()

st.title("🧩 Implementation Proposal")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før Implementation Proposal.")
    st.stop()

render_implementation_proposal()

proposal_result = st.session_state.get("implementation_proposal_result")
if isinstance(proposal_result, Mapping):
    st.page_link(
        "pages/05_Patch_Review_And_Apply.py",
        label="Gennemgå proposal og anmod om governed apply",
        icon="🛡️",
    )
