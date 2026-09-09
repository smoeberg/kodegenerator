"""DOR / Guide — canonical Streamlit shell.

This is the single GUI entrypoint. User-facing work is organized around Overblik,
Mit arbejde, Sager and Søg. Technical execution/evidence tools remain available
contextually inside case/search views while backend APIs retain authority.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

st.set_page_config(
    page_title="DOR / Guide",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_shell_actions import stop_realtime
from dashboard.case_shell_views import cases_view, overview, search_view, work_view
from dashboard.case_workbench import build_case_workbench
from dashboard.context_navigation import (
    render_sidebar_organization_switcher,
    sync_organization_context,
)
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration
from dashboard.state import authenticated, clear_auth, init_state

WORK_NAV = ("Overblik", "Mit arbejde", "Sager", "Søg")
ADMIN_NAV = ("Ingen", "Governance", "Integration")

init_state()


def _css() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#17333c; --muted:#71878b; --nav:#15343d;
                --paper:#f7f5ee; --card:#fffdf8; --line:#dbe2dc;
                --teal:#2d8877; --coral:#df7867; }
        .stApp { background:var(--paper); color:var(--ink); }
        [data-testid="stHeader"] { background:transparent; }
        [data-testid="stSidebar"] { background:var(--nav); }
        [data-testid="stSidebar"] * { color:#eef5f2 !important; }
        .block-container { max-width:1240px; padding-top:2.5rem; padding-bottom:4rem; }
        .eyebrow { color:var(--muted); font-size:.68rem; letter-spacing:.15em;
                   text-transform:uppercase; font-weight:800; }
        .subtitle { color:var(--muted); margin-top:-.35rem; margin-bottom:1.35rem; }
        .card { background:var(--card); border:1px solid var(--line);
                border-radius:18px; padding:1.2rem 1.25rem; }
        .metric { min-height:112px; }
        .metric-label { color:var(--muted); font-size:.73rem; font-weight:750; }
        .metric-value { color:var(--ink); font-size:1.8rem; font-weight:800; margin:.45rem 0 .15rem; }
        .metric-foot { color:#8a999b; font-size:.7rem; }
        .attention { background:#eef5f0; border-radius:14px; padding:1rem 1.1rem; }
        .warning { background:#fff1ec; border:1px solid #f0d2ca; border-radius:14px; padding:1rem 1.1rem; }
        .status-pill { display:inline-block; background:#f5dfd9; color:#a95748;
                       border-radius:999px; padding:.32rem .65rem; font-size:.68rem; font-weight:800; }
        .lifecycle { display:grid; grid-template-columns:repeat(6,1fr); gap:.4rem; margin:1.2rem 0 1rem; }
        .life { text-align:center; color:var(--muted); font-size:.7rem; font-weight:750; }
        .life-dot { width:30px; height:30px; margin:0 auto .45rem; border-radius:50%;
                     border:1px solid #cddbd6; display:flex; align-items:center;
                     justify-content:center; background:#f8faf6; }
        .life.done .life-dot { background:var(--teal); border-color:var(--teal); color:#fff; }
        .life.current .life-dot { background:#f9e3de; border:2px solid var(--coral); color:var(--ink); }
        .nav-brand { padding:.5rem 0 1.2rem; font-size:1.05rem; font-weight:800; }
        .nav-section { color:#9eb5b8 !important; font-size:.62rem; letter-spacing:.14em;
                       text-transform:uppercase; margin:.9rem 0 .35rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def api() -> DORAPIClient:
    return DORAPIClient(token=st.session_state.get("access_token"))


def _get_projects(client: DORAPIClient, organization_id: str) -> list[dict[str, Any]]:
    payload = client.get(
        "/api/v1/control-plane/projects",
        params={"organization_id": organization_id},
    )
    rows = payload.get("projects", []) if isinstance(payload, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _get_executions(client: DORAPIClient) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = client.get("/api/v1/execution")
        rows = payload if isinstance(payload, list) else []
        return [dict(row) for row in rows if isinstance(row, Mapping)], None
    except DORAPIError as exc:
        return [], f"Execution-data er midlertidigt utilgængelige ({exc.status_code})."


def _sidebar(client: DORAPIClient) -> str:
    if st.session_state.get("operator_nav") not in WORK_NAV:
        st.session_state["operator_nav"] = "Overblik"
    if st.session_state.get("operator_admin_nav") not in ADMIN_NAV:
        st.session_state["operator_admin_nav"] = "Ingen"

    with st.sidebar:
        st.markdown('<div class="nav-brand">DOR / Guide</div>', unsafe_allow_html=True)
        st.markdown('<div class="nav-section">Arbejde</div>', unsafe_allow_html=True)
        nav = st.radio(
            "Navigation",
            WORK_NAV,
            label_visibility="collapsed",
            key="operator_nav",
        )

        st.markdown('<div class="nav-section">Organisation</div>', unsafe_allow_html=True)
        try:
            sync_organization_context(client)
            render_sidebar_organization_switcher(client)
        except DORAPIError as exc:
            st.caption(f"Organisation kunne ikke hentes ({exc.status_code}).")

        st.markdown('<div class="nav-section">Administration</div>', unsafe_allow_html=True)
        admin = st.radio(
            "Administration",
            ADMIN_NAV,
            label_visibility="collapsed",
            key="operator_admin_nav",
        )
        if admin != "Ingen":
            nav = admin

        st.divider()
        st.caption(st.session_state.get("username") or "—")
        if st.button("Log ud", use_container_width=True):
            stop_realtime()
            clear_auth()
            st.rerun()
    return nav


def _login() -> None:
    st.markdown(
        '<div class="eyebrow">DIGITAL ORGANIZATION RUNTIME</div>',
        unsafe_allow_html=True,
    )
    st.title("DOR / Guide")
    st.markdown(
        '<div class="subtitle">Hvad kræver din opmærksomhed, og hvad er næste handling?</div>',
        unsafe_allow_html=True,
    )
    with st.form("login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        if st.form_submit_button("Log ind", type="primary"):
            try:
                client = DORAPIClient()
                st.session_state["access_token"] = client.login(username, password)
                st.session_state["username"] = username
                st.rerun()
            except DORAPIError as exc:
                st.error(f"Login fejlede ({exc.status_code}): {exc}")


def _governance_view(client: DORAPIClient) -> None:
    st.markdown(
        '<div class="eyebrow">OPERATØRCENTER / GOVERNANCE</div>'
        '<h1>Governance</h1>'
        '<div class="subtitle">Organisationens bot-, rolle- og policyflader.</div>',
        unsafe_allow_html=True,
    )
    render_multi_bot_control_plane(client, st.session_state.get("organization_id") or "")


def _integration_view(client: DORAPIClient) -> None:
    st.markdown(
        '<div class="eyebrow">OPERATØRCENTER / INTEGRATION</div>'
        '<h1>Integration</h1>'
        '<div class="subtitle">Eksterne systemer håndteres gennem API-backed integration surfaces.</div>',
        unsafe_allow_html=True,
    )
    render_redmine_integration(client)


def main() -> None:
    _css()
    if not authenticated():
        _login()
        return

    client = api()
    nav = _sidebar(client)
    organization_id = st.session_state.get("organization_id")
    projects: list[dict[str, Any]] = []
    if organization_id:
        try:
            projects = _get_projects(client, organization_id)
        except DORAPIError as exc:
            st.error(f"Sagsdata kunne ikke hentes ({exc.status_code}).")

    executions, execution_error = _get_executions(client)
    snapshot = build_case_workbench(projects, executions)

    if nav not in {"Sager", "Søg"}:
        st.session_state.pop("technical_workflow_id", None)
        stop_realtime()

    if nav == "Overblik":
        overview(client, snapshot, execution_error)
    elif nav == "Mit arbejde":
        work_view(snapshot)
    elif nav == "Sager":
        cases_view(client, snapshot)
    elif nav == "Søg":
        search_view(client, snapshot)
    elif nav == "Governance":
        _governance_view(client)
    elif nav == "Integration":
        _integration_view(client)


if __name__ == "__main__":
    main()
