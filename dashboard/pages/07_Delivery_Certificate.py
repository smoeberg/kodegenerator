"""Streamlit page for authoritative Delivery Contract v1 certification."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient
from dashboard.delivery_certification import render_delivery_certification
from dashboard.state import authenticated, init_state


st.set_page_config(
    page_title="DOR Delivery Certificate",
    page_icon="✅",
    layout="wide",
)
init_state()

st.title("✅ Delivery Certificate")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før delivery certification.")
    st.stop()

render_delivery_certification(
    DORAPIClient(token=st.session_state.get("access_token"))
)
