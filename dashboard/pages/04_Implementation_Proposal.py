"""Streamlit page for governed Implementation Agent patch proposals."""
from __future__ import annotations

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
