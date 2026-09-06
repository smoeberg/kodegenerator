"""Streamlit page for governed post-audit requirements and AI-6 planning."""
from __future__ import annotations

import streamlit as st

from dashboard.project_planning import render_project_planning
from dashboard.state import authenticated, init_state

st.set_page_config(page_title="DOR Requirements & Plan", page_icon="🧭", layout="wide")
init_state()

st.title("🧭 Requirements & Plan")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før planning.")
    st.stop()

render_project_planning()
