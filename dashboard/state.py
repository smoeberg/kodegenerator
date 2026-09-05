"""Streamlit bootstrap and session-state helpers."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.build_identity import current_build_identity


DEFAULTS = {
    "access_token": None,
    "username": None,
    "organization_id": None,
    "selected_project_id": None,
    "selected_project_fingerprint": None,
    "selected_workflow_id": None,
    "realtime_status": "offline",
}


def init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)

    identity = current_build_identity()
    revision = identity.short_revision or "ukendt"
    st.sidebar.caption(
        f"DOR build `{identity.short_fingerprint}` · revision `{revision}`"
    )

    token = st.session_state.get("access_token")
    if token:
        # Bootstrap the tenant/project context from the authenticated API rather
        # than decoding JWT claims or requiring a manual organization input.
        from dashboard.context_navigation import sync_organization_context

        try:
            sync_organization_context(DORAPIClient(token=token))
        except DORAPIError as exc:
            if exc.status_code == 401:
                clear_auth()
        except Exception:
            # Context navigation is a read-only convenience surface. Transport
            # failure must not suppress the existing manual API/cockpit paths.
            pass


def clear_auth() -> None:
    st.session_state["access_token"] = None
    st.session_state["username"] = None
    st.session_state["organization_id"] = None
    st.session_state["selected_project_id"] = None
    st.session_state["selected_project_fingerprint"] = None
    st.session_state["selected_workflow_id"] = None
    st.session_state.pop("workflow_input", None)
    st.session_state.pop("project_context_catalog", None)


def authenticated() -> bool:
    return bool(st.session_state.get("access_token"))
