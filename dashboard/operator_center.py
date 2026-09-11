"""DOR / Guide — canonical Streamlit shell.

The shell is situation-first: user work is organized around Overblik, Mit arbejde,
Sager and Søg. Administration is a backend-authorized capability inside the same
Operator GUI deployment.
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

from dashboard.admin_access import fetch_organization_admin_status
from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_shell_actions import stop_realtime
from dashboard.case_shell_views import cases_view, overview, search_view, work_view
from dashboard.case_workbench import build_case_workbench
from dashboard.context_navigation import (
    render_sidebar_organization_switcher,
    sync_organization_context,
)
from dashboard.settings_view import render_settings
from dashboard.state import authenticated, clear_auth, init_state
from dashboard.user_feedback import explain_api_error, render_api_error

WORK_NAV = ("Overblik", "Mit arbejde", "Sager", "Søg")
ADMIN_NAV = ("Ingen", "Administration")

init_state()


def _css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#15343d; --muted:#71878b; --nav:#143943;
          --paper:#f8f6ef; --card:#fffefa; --line:#dde5df;
          --teal:#2d8877; --teal-soft:#e9f3ef; --coral:#df7867;
          --coral-soft:#fff0eb; --shadow:0 10px 30px rgba(23,51,60,.05);
        }
        .stApp { background:var(--paper); color:var(--ink); }
        [data-testid="stHeader"] { background:transparent; }
        [data-testid="stSidebar"] { background:var(--nav); }
        [data-testid="stSidebar"] * { color:#eef5f2 !important; }
        .block-container {
          max-width:1180px; padding-top:2.7rem; padding-bottom:5rem;
        }
        h1 { letter-spacing:-.035em; margin-bottom:.35rem !important; }
        h2, h3 { letter-spacing:-.02em; }
        .eyebrow, .section-label {
          color:var(--muted); font-size:.66rem; letter-spacing:.16em;
          text-transform:uppercase; font-weight:800;
        }
        .section-label { margin:1.25rem 0 .55rem; }
        .subtitle {
          color:var(--muted); max-width:780px; margin-top:-.15rem;
          margin-bottom:1.55rem; font-size:1.02rem;
        }
        .hero-question {
          font-size:1.55rem; font-weight:760; margin:.55rem 0 .2rem;
          letter-spacing:-.025em;
        }
        .card, div[data-testid="stVerticalBlockBorderWrapper"] {
          background:var(--card);
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
          border-color:var(--line) !important;
          border-radius:20px !important;
          box-shadow:var(--shadow);
        }
        .attention {
          background:var(--teal-soft); border:1px solid #d3e7df;
          border-radius:18px; padding:1.15rem 1.2rem;
        }
        .attention-kicker {
          color:#5f7f77; font-size:.62rem; letter-spacing:.13em;
          font-weight:800; margin-bottom:.4rem;
        }
        .attention-title {
          color:var(--ink); font-size:1.22rem; line-height:1.25;
          font-weight:800; margin-bottom:.35rem;
        }
        .attention-copy { color:#526b70; line-height:1.5; }
        .next-action {
          margin-top:.65rem; border-left:4px solid var(--teal);
          padding:.65rem .9rem; background:#fff;
          border-radius:0 12px 12px 0;
        }
        .next-action-label {
          font-size:1.03rem; font-weight:800; color:var(--ink);
        }
        .next-action-why {
          color:var(--muted); font-size:.78rem; margin-top:.2rem;
        }
        .status-pill {
          display:inline-block; background:var(--coral-soft); color:#9b5649;
          border-radius:999px; padding:.32rem .65rem; font-size:.66rem;
          font-weight:800; margin-bottom:.55rem;
        }
        .quiet-pill { background:var(--teal-soft); color:#397060; }
        .lifecycle {
          display:grid; grid-template-columns:repeat(6,1fr); gap:.45rem;
          margin:1rem 0 1.35rem;
        }
        .life {
          text-align:center; color:var(--muted); font-size:.68rem;
          font-weight:750; line-height:1.25;
        }
        .life-dot {
          width:31px; height:31px; margin:0 auto .45rem; border-radius:50%;
          border:1px solid #ccd9d4; display:flex; align-items:center;
          justify-content:center; background:#fbfcf8;
        }
        .life.done .life-dot {
          background:var(--teal); border-color:var(--teal); color:#fff;
        }
        .life.current .life-dot {
          background:var(--coral-soft); border:2px solid var(--coral);
          color:var(--ink);
        }
        .nav-brand {
          padding:.6rem 0 1.25rem; font-size:1.05rem; font-weight:800;
        }
        .nav-section {
          color:#9eb5b8 !important; font-size:.61rem; letter-spacing:.14em;
          text-transform:uppercase; margin:1rem 0 .35rem;
        }
        div[data-testid="stMetric"] {
          background:transparent; border:0; padding:.35rem 0;
        }
        div[data-testid="stMetricValue"] { font-size:1.45rem; }
        div[data-testid="stAlert"] { border-radius:14px; }
        .stButton > button {
          border-radius:12px; min-height:2.65rem; font-weight:700;
        }
        @media (max-width: 900px) {
          .lifecycle { grid-template-columns:repeat(3,1fr); row-gap:1rem; }
        }
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
        feedback = explain_api_error(exc)
        return [], f"{feedback.title}. {feedback.next_step}"


def _copy_widget_to_logical(widget_key: str, logical_key: str) -> None:
    st.session_state[logical_key] = st.session_state.get(widget_key)


def _sync_radio_state(
    *,
    logical_key: str,
    widget_key: str,
    allowed: tuple[str, ...],
    default: str,
) -> None:
    """Sync logical navigation before Streamlit instantiates the radio widget.

    Buttons rendered later in a run may safely change the logical key. On the
    next rerun we copy that value into the widget-owned key before the widget
    exists, avoiding Streamlit's post-instantiation session-state exception.
    """
    logical = st.session_state.get(logical_key)
    if logical not in allowed:
        logical = default
        st.session_state[logical_key] = logical
    if st.session_state.get(widget_key) != logical:
        st.session_state[widget_key] = logical


def _sidebar(client: DORAPIClient) -> tuple[str, bool | None]:
    _sync_radio_state(
        logical_key="operator_nav",
        widget_key="operator_nav_widget",
        allowed=WORK_NAV,
        default="Overblik",
    )
    _sync_radio_state(
        logical_key="operator_admin_nav",
        widget_key="operator_admin_nav_widget",
        allowed=ADMIN_NAV,
        default="Ingen",
    )

    admin_status: bool | None = None
    with st.sidebar:
        st.markdown('<div class="nav-brand">DOR / Guide</div>', unsafe_allow_html=True)
        st.markdown('<div class="nav-section">Arbejde</div>', unsafe_allow_html=True)
        nav = st.radio(
            "Navigation",
            WORK_NAV,
            label_visibility="collapsed",
            key="operator_nav_widget",
            on_change=_copy_widget_to_logical,
            args=("operator_nav_widget", "operator_nav"),
        )
        st.session_state["operator_nav"] = nav

        st.markdown('<div class="nav-section">Organisation</div>', unsafe_allow_html=True)
        try:
            sync_organization_context(client)
            render_sidebar_organization_switcher(client)
        except DORAPIError as exc:
            feedback = explain_api_error(exc)
            st.caption(f"{feedback.title}. {feedback.next_step}")

        organization_id = str(st.session_state.get("organization_id") or "").strip()
        if organization_id:
            try:
                admin_status = fetch_organization_admin_status(client, organization_id)
            except DORAPIError:
                admin_status = None
            except Exception:
                admin_status = None

        if admin_status is True:
            st.markdown(
                '<div class="nav-section">Administration</div>',
                unsafe_allow_html=True,
            )
            admin = st.radio(
                "Administration",
                ADMIN_NAV,
                label_visibility="collapsed",
                key="operator_admin_nav_widget",
                on_change=_copy_widget_to_logical,
                args=("operator_admin_nav_widget", "operator_admin_nav"),
            )
            st.session_state["operator_admin_nav"] = admin
            if admin == "Administration":
                nav = "Administration"
        else:
            # Never preserve a privileged client-side selection once the
            # authoritative admin projection is false or unknown.
            st.session_state["operator_admin_nav"] = "Ingen"
            st.session_state["operator_admin_nav_widget"] = "Ingen"
            if organization_id and admin_status is None:
                st.markdown(
                    '<div class="nav-section">Administration</div>',
                    unsafe_allow_html=True,
                )
                st.caption("Status kan ikke fastslås")

        st.divider()
        st.caption(st.session_state.get("username") or "—")
        if st.button("Log ud", use_container_width=True):
            stop_realtime()
            clear_auth()
            st.rerun()
    return nav, admin_status


def _login() -> None:
    st.markdown(
        '<div class="eyebrow">DIGITAL ORGANIZATION RUNTIME</div>',
        unsafe_allow_html=True,
    )
    st.title("DOR / Guide")
    st.markdown(
        '<div class="hero-question">Hvad vil du have DOR til at hjælpe med?</div>'
        '<div class="subtitle">Log ind for at se situationer, næste handlinger og evidens.</div>',
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
                if exc.status_code == 401:
                    st.error("Brugernavn eller adgangskode blev ikke godkendt. Prøv igen.")
                else:
                    render_api_error(
                        exc,
                        key="login",
                        operation="Login kunne ikke gennemføres",
                        technical_details=False,
                    )


def _render_no_organization_state() -> None:
    st.markdown(
        '<div class="eyebrow">DOR / KOM I GANG</div>'
        '<h1>Vælg en organisation</h1>'
        '<div class="subtitle">DOR skal kende din organisation, før sager, ansvar og evidens kan bindes korrekt.</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.subheader("Organisationen er dit arbejdsrum")
        st.write(
            "Kun organisationer, som backenden har knyttet til din bruger, kan vælges her. "
            "Hvis du mangler adgang, skal en eksisterende administrator tilknytte dig."
        )


def _render_admin_denied(admin_status: bool | None) -> None:
    if admin_status is None:
        st.error("Status kan ikke fastslås")
        st.caption(
            "DOR kunne ikke bekræfte administratorstatus fra backenden. "
            "Ingen administrative handlinger vises eller udføres."
        )
    else:
        st.error("Administration er ikke tilgængelig for denne bruger.")


def main() -> None:
    _css()
    if not authenticated():
        _login()
        return

    client = api()
    nav, admin_status = _sidebar(client)
    organization_id = st.session_state.get("organization_id")

    if nav == "Administration":
        stop_realtime()
        if admin_status is not True:
            _render_admin_denied(admin_status)
            return
        render_settings(client)
        return

    if nav in WORK_NAV and not organization_id:
        stop_realtime()
        _render_no_organization_state()
        return

    projects: list[dict[str, Any]] = []
    if organization_id:
        try:
            projects = _get_projects(client, organization_id)
        except DORAPIError as exc:
            render_api_error(exc, key="case-catalog", operation="Sagerne kunne ikke hentes")

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


if __name__ == "__main__":
    main()
