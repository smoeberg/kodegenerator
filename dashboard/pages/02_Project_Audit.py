"""Streamlit page for the governed Project Audit flow."""
from __future__ import annotations

import streamlit as st

from dashboard.project_audit import render_project_audit
from dashboard.state import authenticated, init_state


st.set_page_config(page_title="DOR Project Audit", page_icon="🔎", layout="wide")
init_state()

st.title("🔎 Project Audit")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før Project Audit.")
    st.stop()

render_project_audit()
