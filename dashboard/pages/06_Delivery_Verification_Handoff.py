"""Streamlit page for a pending post-apply delivery verification handoff."""
from __future__ import annotations

import streamlit as st

from dashboard.delivery_verification import render_delivery_verification_handoff
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Delivery Verification Handoff",
    page_icon="📦",
    layout="wide",
)
init_state()

st.title("📦 Delivery Verification Handoff")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før delivery verification handoff.")
    st.stop()

render_delivery_verification_handoff()
