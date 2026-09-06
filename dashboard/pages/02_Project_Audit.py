"""Streamlit page for the governed Project Audit flow."""
from __future__ import annotations

from typing import Mapping

import streamlit as st

from dashboard.project_audit import render_project_audit
from dashboard.state import authenticated, init_state
from phase4.onboarding import OnboardingPurpose


st.set_page_config(page_title="DOR Project Audit", page_icon="🔎", layout="wide")
init_state()

st.title("🔎 Project Audit")
if not authenticated():
    st.warning("Log ind på DOR Control Plane-forsiden før Project Audit.")
    st.stop()

render_project_audit()

audit_result = st.session_state.get("project_audit_result")
onboarding_result = st.session_state.get("onboarding_intent_result")
intent_payload = (
    onboarding_result.get("intent", {})
    if isinstance(onboarding_result, Mapping)
    else {}
)
if (
    isinstance(audit_result, Mapping)
    and isinstance(intent_payload, Mapping)
    and audit_result.get("intent_id") == intent_payload.get("intent_id")
    and audit_result.get("purpose") != OnboardingPurpose.AUDIT_ONLY.value
    and audit_result.get("delivery_allowed") is True
):
    st.page_link(
        "pages/03_Requirements_And_Plan.py",
        label="Fortsæt til Requirements & Plan",
        icon="🧭",
    )
