"""Streamlit page for governed repository onboarding."""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient
from dashboard.onboarding import render_onboarding
from dashboard.state import authenticated, init_state

st.set_page_config(page_title="DOR Onboarding", page_icon="🧭", layout="wide")
init_state()

st.title("🧭 Onboarding")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før onboarding.")
    st.stop()

client = DORAPIClient(token=st.session_state.get("access_token"))
render_onboarding(client)
