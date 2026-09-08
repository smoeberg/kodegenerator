"""DOR / Guide operator center.

Presentation-only UI over the authenticated FastAPI Control Plane. Workflow
authority, authorization and persistence remain in the backend.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_lifecycle import render_cockpit_lifecycle
from dashboard.cockpit_view_model import (
    build_evidence_trace,
    gate_decision_payload,
    gate_rework_payload,
    gate_retry_payload,
    normalize_gates,
)
from dashboard.context_navigation import (
    render_sidebar_organization_switcher,
    sync_organization_context,
)
from dashboard.evidence_trace import render_evidence_trace
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration
from dashboard.realtime import WorkflowRealtime
from dashboard.state import authenticated, clear_auth, init_state
from dashboard.ui_primitives import format_timestamp, status_badge

st.set_page_config(
    page_title="DOR / Guide",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="expanded",
)
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
        .lifecycle { display:grid; grid-template-columns:repeat(5,1fr); gap:.4rem; margin:1.2rem 0 1rem; }
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


def _greeting() -> str:
    hour = datetime.now(ZoneInfo("Europe/Copenhagen")).hour
    if 5 <= hour < 12:
        return "Godmorgen"
    if 12 <= hour < 18:
        return "Goddag"
    return "Godaften"


def _metric(label: str, value: object, foot: str) -> None:
    st.markdown(
        f'<div class="card metric"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-foot">{foot}</div></div>',
        unsafe_allow_html=True,
    )


def _stage(state: str) -> int:
    value = state.lower()
    if any(x in value for x in ("requirement", "analysis", "intent")):
        return 1
    if any(x in value for x in ("architecture", "contract", "generat", "implement", "build", "test", "execute")):
        return 2
    if any(x in value for x in ("gate", "review", "approval", "decision")):
        return 3
    if any(x in value for x in ("release", "deliver", "certif")):
        return 4
    return 0


def _get_projects(client: DORAPIClient, organization_id: str) -> list[dict[str, Any]]:
    payload = client.get(
        "/api/v1/control-plane/projects",
        params={"organization_id": organization_id},
    )
    rows = payload.get("projects", []) if isinstance(payload, Mapping) else []
    return [dict(x) for x in rows if isinstance(x, Mapping)]


def _get_executions(client: DORAPIClient) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = client.get("/api/v1/execution")
        rows = payload if isinstance(payload, list) else []
        return [dict(x) for x in rows if isinstance(x, Mapping)], None
    except DORAPIError as exc:
        return [], f"Execution-data er midlertidigt utilgængelige ({exc.status_code})."


def _sidebar(client: DORAPIClient) -> str:
    with st.sidebar:
        st.markdown('<div class="nav-brand">DOR / Guide</div>', unsafe_allow_html=True)
        st.markdown('<div class="nav-section">Arbejde</div>', unsafe_allow_html=True)
        nav = st.radio(
            "Navigation",
            ["Overblik", "Beslutninger", "Projekter", "Execution", "Evidens"],
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
            ["Ingen", "Governance", "Integration"],
            label_visibility="collapsed",
            key="operator_admin_nav",
        )
        if admin != "Ingen":
            nav = admin
        st.divider()
        st.caption(st.session_state.get("username") or "—")
        if st.button("Log ud", use_container_width=True):
            _stop_realtime()
            clear_auth()
            st.rerun()
    return nav


def _stop_realtime() -> None:
    manager = st.session_state.get("realtime_manager")
    if isinstance(manager, WorkflowRealtime):
        manager.stop()
    st.session_state["realtime_manager"] = None
    st.session_state["realtime_workflow_id"] = None
    st.session_state["realtime_status"] = "offline"


def _ensure_realtime(workflow_id: str) -> WorkflowRealtime:
    manager = st.session_state.get("realtime_manager")
    if st.session_state.get("realtime_workflow_id") != workflow_id or not isinstance(manager, WorkflowRealtime):
        if isinstance(manager, WorkflowRealtime):
            manager.stop()
        manager = WorkflowRealtime(api(), workflow_id)
        st.session_state["realtime_manager"] = manager
        st.session_state["realtime_workflow_id"] = workflow_id
        manager.start()
    st.session_state["realtime_status"] = manager.status
    return manager


@st.fragment(run_every="1s")
def _realtime_pump(workflow_id: str) -> None:
    manager = st.session_state.get("realtime_manager")
    if not isinstance(manager, WorkflowRealtime) or manager.workflow_id != workflow_id:
        return
    events = manager.drain()
    st.session_state["realtime_status"] = manager.status
    if manager.status == "unauthorized":
        _stop_realtime()
        clear_auth()
        st.rerun()
    if events:
        st.session_state["last_realtime_event"] = events[-1].event_type
        st.session_state["realtime_event_count"] = st.session_state.get("realtime_event_count", 0) + len(events)
        st.rerun()


def _login() -> None:
    st.markdown('<div class="eyebrow">DIGITAL ORGANIZATION RUNTIME</div>', unsafe_allow_html=True)
    st.title("DOR / Guide")
    st.markdown('<div class="subtitle">Det samlede operatørcenter for projekter, beslutninger, execution og evidens.</div>', unsafe_allow_html=True)
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


def _overview(
    client: DORAPIClient,
    projects: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    execution_error: str | None,
) -> None:
    active = [x for x in executions if not x.get("terminal")]
    decisions = [x for x in active if x.get("action_required") in {"human_decision", "rejected"}]
    blocked = [x for x in active if x.get("blocking_gate")]
    selected_id = st.session_state.get("selected_project_id")
    selected = next((p for p in projects if p.get("project_id") == selected_id), None)
    if selected is None and projects:
        selected = projects[0]
        st.session_state["selected_project_id"] = selected.get("project_id")
    linked = [x for x in executions if selected and x.get("project_id") == selected.get("project_id")]
    execution = next(iter(linked), next(iter(active), None))

    st.markdown(
        f'<div class="eyebrow">OPERATØRCENTER / OVERBLIK</div>'
        f'<h1>{_greeting()}, {st.session_state.get("username") or "operatør"}</h1>'
        '<div class="subtitle">Her er det, der kræver din opmærksomhed først.</div>',
        unsafe_allow_html=True,
    )
    if execution_error:
        st.markdown(
            f'<div class="warning"><b>Execution-data er midlertidigt utilgængelige.</b><br>{execution_error} '
            'Projekter, organisation og øvrige API-flader vises stadig.</div>',
            unsafe_allow_html=True,
        )
        st.write("")

    cols = st.columns(4)
    with cols[0]:
        _metric("Aktive executions", len(active), f"{len(projects)} projekter")
    with cols[1]:
        _metric("Åbne beslutninger", len(decisions), "Backend-ejede gates")
    with cols[2]:
        _metric("Gennemløb", len(executions), f"{len(executions)-len(active)} afsluttede")
    with cols[3]:
        _metric("Blokerede", len(blocked), "Kræver backend-tilladt handling")

    left, right = st.columns([2.1, 1])
    with left:
        if selected:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            if execution and execution.get("action_required") in {"human_decision", "rejected"}:
                st.markdown('<span class="status-pill">Kræver menneske</span>', unsafe_allow_html=True)
            st.subheader(selected.get("name", "Projekt"))
            st.caption(f"{selected.get('description') or 'Kundeprojekt'} · {status_badge(selected.get('status'))}")
            if execution:
                current = _stage(str(execution.get("current_state") or ""))
                labels = ["Idé", "Plan", "Arbejde", "Beslutning", "Levering"]
                html = '<div class="lifecycle">'
                for i, label in enumerate(labels):
                    cls = "done" if i < current else ("current" if i == current else "")
                    mark = "✓" if i < current else str(i + 1)
                    html += f'<div class="life {cls}"><div class="life-dot">{mark}</div>{label}</div>'
                html += "</div>"
                st.markdown(html, unsafe_allow_html=True)
                st.progress((current + 1) / 5)
                action = str(execution.get("action_required") or "none")
                text = {
                    "human_decision": "Læs beslutningssporet og tag kun den beslutning, som backend har åbnet.",
                    "rejected": "Gennemgå afvisningen. Rework/retry vises kun, når backend tillader det.",
                    "rework_active": "Governed rework er i gang. Vent på backend-resultatet.",
                    "work_in_progress": "Arbejdet kører. Følg execution og evidens.",
                    "terminal": "Execution er afsluttet. Gennemgå leveringsbeviset.",
                }.get(action, "Ingen human handling kræves lige nu.")
                st.markdown(f'<div class="attention"><b>Operatørens næste</b><br>{text}</div>', unsafe_allow_html=True)
                a, b = st.columns(2)
                with a:
                    if st.button("Åbn projekt", type="primary", use_container_width=True):
                        st.session_state["operator_nav"] = "Projekter"
                        st.rerun()
                with b:
                    if st.button("Åbn execution", use_container_width=True):
                        st.session_state["selected_workflow_id"] = execution.get("workflow_id")
                        st.session_state["operator_nav"] = "Execution"
                        st.rerun()
            else:
                st.info("Projektet er oprettet, men backend rapporterer endnu ingen tilknyttet execution.")
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.subheader("Ingen projekter endnu")
            st.write("Opret det første projekt fra Projekter. GUI'en sender intent gennem Control Plane API.")
            if st.button("Opret projekt", type="primary"):
                st.session_state["operator_nav"] = "Projekter"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card"><div class="eyebrow">SYSTEMHELDBRED</div><h2>Systemstatus</h2>', unsafe_allow_html=True)
        try:
            ready = client.readiness()
            state = ready.get("status", "unknown") if isinstance(ready, Mapping) else "unknown"
            st.metric("API / database", state.upper())
        except DORAPIError as exc:
            st.error(f"Readiness ({exc.status_code})")
        try:
            ops = client.get("/api/v1/swarm/ops/health")
            if isinstance(ops, Mapping):
                for name, value in ops.items():
                    state = value.get("status", value) if isinstance(value, Mapping) else value
                    st.caption(f"{name}: {state}")
        except DORAPIError:
            st.caption("Operations health ikke tilgængelig.")
        st.caption("Status kommer direkte fra backend health surfaces.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    st.subheader("Seneste hændelser")
    if executions:
        rows = [
            {
                "Projekt": x.get("project_name", "—"),
                "State": x.get("current_state", "—"),
                "Handling": x.get("action_required", "none"),
                "Opdateret": format_timestamp(x.get("updated_at")),
            }
            for x in executions[:8]
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen execution-hændelser rapporteret af backend.")


def _projects_view(client: DORAPIClient, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / PROJEKTER</div><h1>Projekter</h1><div class="subtitle">Intent og launch håndteres af Control Plane API.</div>', unsafe_allow_html=True)
    for project in projects:
        with st.container(border=True):
            top = st.columns([3, 1, 1])
            with top[0]:
                st.subheader(project.get("name", project.get("project_id", "Projekt")))
                st.caption(project.get("description") or "Ingen beskrivelse")
            with top[1]:
                st.metric("Status", str(project.get("status", "unknown")))
            with top[2]:
                if st.button("Vælg", key=f"select-{project.get('project_id')}", use_container_width=True):
                    st.session_state["selected_project_id"] = project.get("project_id")
                    st.rerun()
            st.caption(f"ID `{project.get('project_id')}` · fingerprint `{str(project.get('project_fingerprint',''))[:20]}…`")
            if project.get("status") == "created":
                with st.expander("Governed launch"):
                    st.warning("Launch sender en fingerprint-bundet command til Control Plane. Den starter ikke en lokal workflow-engine i GUI'en.")
                    if st.button("Request launch", key=f"launch-{project.get('project_id')}", type="primary"):
                        try:
                            result = client.post(
                                f"/api/v1/control-plane/projects/{project['project_id']}/launch",
                                json={
                                    "organization_id": project["organization_id"],
                                    "command_id": str(uuid4()),
                                    "expected_project_fingerprint": project["project_fingerprint"],
                                },
                            )
                            st.success("Launch request accepteret af Control Plane.")
                            st.json(result)
                        except DORAPIError as exc:
                            st.error(f"Launch afvist ({exc.status_code}): {exc}")

    with st.expander("Opret nyt projekt"):
        with st.form("create-project"):
            name = st.text_input("Navn")
            goal = st.text_area("Mål")
            description = st.text_area("Beskrivelse")
            priority = st.selectbox("Prioritet", ["low", "medium", "high", "critical"], index=1)
            constraints = st.text_area("Begrænsninger", help="Én nøgle=værdi pr. linje")
            capabilities = st.text_area("Påkrævede capabilities", help="Én pr. linje")
            submit = st.form_submit_button("Opret projekt", type="primary")
        if submit:
            org = st.session_state.get("organization_id")
            if not org or not name.strip() or not goal.strip():
                st.warning("Organisation, navn og mål er påkrævet.")
            else:
                constraint_map: dict[str, str] = {}
                for line in constraints.splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        constraint_map[key.strip()] = value.strip()
                try:
                    result = client.post(
                        "/api/v1/control-plane/projects",
                        json={
                            "organization_id": org,
                            "name": name.strip(),
                            "command_id": str(uuid4()),
                            "description": description.strip(),
                            "intent": {
                                "goal": goal.strip(),
                                "description": description.strip(),
                                "priority": priority,
                                "constraints": constraint_map,
                                "required_capabilities": list(dict.fromkeys(x.strip() for x in capabilities.splitlines() if x.strip())),
                            },
                        },
                    )
                    project = result.get("project", result)
                    st.session_state["selected_project_id"] = project.get("project_id")
                    st.success("Projekt oprettet gennem Control Plane API.")
                    st.rerun()
                except DORAPIError as exc:
                    st.error(f"API-fejl ({exc.status_code}): {exc}")


def _decisions_view(client: DORAPIClient, executions: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / BESLUTNINGER</div><h1>Beslutninger</h1><div class="subtitle">Human-in-the-loop uden lokal workflow-logik. Kun backend-åbnede gates kan handles.</div>', unsafe_allow_html=True)
    candidates = [x for x in executions if x.get("action_required") in {"human_decision", "rejected"}]
    if not candidates:
        st.success("Ingen åbne beslutninger kræver menneskelig handling.")
        return
    for item in candidates:
        workflow_id = str(item["workflow_id"])
        try:
            gates = normalize_gates(client.get(f"/api/v1/execution/{workflow_id}/gates"))
        except DORAPIError as exc:
            st.error(f"Gates kunne ikke hentes ({exc.status_code}).")
            continue
        for gate in gates:
            if gate["status"] not in {"human_required", "rejected"}:
                continue
            with st.container(border=True):
                st.subheader(gate["name"])
                st.caption(f"{item.get('project_name','—')} · workflow `{workflow_id}` · round {gate['round']}")
                st.write(gate["description"])
                if gate["status"] == "human_required":
                    a, b = st.columns(2)
                    with a:
                        if st.button("Godkend anbefaling", key=f"approve-{workflow_id}-{gate['id']}", type="primary", use_container_width=True):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json=gate_decision_payload(gate["id"], "approved"))
                                st.success("Beslutning registreret.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Afvist ({exc.status_code}): {exc}")
                    with b:
                        if st.button("Bed om ændringer", key=f"reject-{workflow_id}-{gate['id']}", use_container_width=True):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json=gate_decision_payload(gate["id"], "rejected"))
                                st.warning("Afvisning registreret; workflowet er fail-closed.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Afvist ({exc.status_code}): {exc}")
                else:
                    st.warning("Denne gate er afvist og blokerer progression.")
                    if gate["can_rework"]:
                        reason = st.text_area("Begrundelse", key=f"rework-reason-{workflow_id}-{gate['id']}", max_chars=2000)
                        if st.button("Bed om ændringer / rework", key=f"rework-{workflow_id}-{gate['id']}"):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/rework", json=gate_rework_payload(gate["id"], reason))
                                st.success("Governed rework køet.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Rework afvist ({exc.status_code}): {exc}")
                    if gate["can_retry"]:
                        reason = st.text_area("Begrundelse for ny round", key=f"retry-reason-{workflow_id}-{gate['id']}", max_chars=2000)
                        if st.button("Åbn ny decision-round", key=f"retry-{workflow_id}-{gate['id']}"):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/retry", json=gate_retry_payload(gate["id"], reason))
                                st.success("Ny round åbnet af backend.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Retry afvist ({exc.status_code}): {exc}")


def _execution_view(client: DORAPIClient) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / EXECUTION</div><h1>Execution</h1><div class="subtitle">Live status, lifecycle, tasks og evidence — med Execution API som eneste authority.</div>', unsafe_allow_html=True)
    workflow_id = st.text_input("Workflow ID", value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id:
        st.info("Vælg en execution fra Overblik, eller indsæt et Workflow ID.")
        return
    workflow_id = workflow_id.strip()
    st.session_state["selected_workflow_id"] = workflow_id
    manager = _ensure_realtime(workflow_id)
    _realtime_pump(workflow_id)
    a, b, c = st.columns(3)
    a.metric("Realtime", manager.status)
    b.metric("Stream events", st.session_state.get("realtime_event_count", 0))
    c.metric("Seneste event", st.session_state.get("last_realtime_event", "—"))
    render_cockpit_lifecycle(client, workflow_id)
    try:
        payload = client.get(f"/api/v1/execution/{workflow_id}")
        if isinstance(payload, Mapping):
            st.subheader("Workflowstatus")
            cols = st.columns(4)
            cols[0].metric("Projekt", payload.get("project_name", "—"))
            cols[1].metric("State", payload.get("current_state", "—"))
            tasks = payload.get("tasks", []) if isinstance(payload.get("tasks"), list) else []
            cols[2].metric("Tasks", len(tasks))
            cols[3].metric("Opdateret", format_timestamp(payload.get("updated_at")))
            if tasks:
                st.dataframe(tasks, use_container_width=True, hide_index=True)
        with st.expander("Evidence trace"):
            try:
                gates = client.get(f"/api/v1/execution/{workflow_id}/gates")
                proposals = client.get(f"/api/v1/execution/{workflow_id}/proposals")
                st.json(build_evidence_trace(payload, gates, proposals))
            except DORAPIError as exc:
                st.warning(f"Evidence trace ikke komplet ({exc.status_code}).")
    except DORAPIError as exc:
        st.error(f"Execution kunne ikke hentes ({exc.status_code}): {exc}")
    render_evidence_trace(client, workflow_id)


def _evidence_view(client: DORAPIClient) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / EVIDENS</div><h1>Evidens</h1><div class="subtitle">Read-only, tenant-scoped evidence. Ingen lokal mutation af evidence.</div>', unsafe_allow_html=True)
    mapping = {
        "Evaluation": "evaluations",
        "Observation": "observations",
        "Snapshot": "snapshots",
        "Work package": "work-packages",
        "Candidate": "candidates",
        "Candidate selection": "candidate-selections",
        "Integration plan": "integration-plans",
        "Integration receipt": "integration-receipts",
    }
    label = st.selectbox("Evidenstype", list(mapping))
    identity = st.text_input("Evidence ID / fingerprint")
    if st.button("Hent evidens", type="primary"):
        if not identity.strip():
            st.warning("Evidence ID er påkrævet.")
            return
        try:
            result = client.get(
                f"/api/v1/bot-evidence/{mapping[label]}/{identity.strip()}",
                params={"organization_id": st.session_state.get("organization_id")},
            )
            st.json(result)
        except DORAPIError as exc:
            st.error(f"Evidence API ({exc.status_code}): {exc}")


def _governance_view(client: DORAPIClient) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / GOVERNANCE</div><h1>Governance</h1><div class="subtitle">Organisationens bot-, rolle- og policyflader.</div>', unsafe_allow_html=True)
    render_multi_bot_control_plane(client, st.session_state.get("organization_id") or "")


def _integration_view(client: DORAPIClient) -> None:
    st.markdown('<div class="eyebrow">OPERATØRCENTER / INTEGRATION</div><h1>Integration</h1><div class="subtitle">Eksterne systemer håndteres gennem de eksisterende API-backed integration surfaces.</div>', unsafe_allow_html=True)
    render_redmine_integration(client)


def main() -> None:
    _css()
    if not authenticated():
        _login()
        return
    client = api()
    nav = _sidebar(client)
    org = st.session_state.get("organization_id")
    projects: list[dict[str, Any]] = []
    if org:
        try:
            projects = _get_projects(client, org)
        except DORAPIError as exc:
            st.error(f"Projektdata kunne ikke hentes ({exc.status_code}).")
    executions, execution_error = _get_executions(client)

    if nav == "Overblik":
        _stop_realtime()
        _overview(client, projects, executions, execution_error)
    elif nav == "Beslutninger":
        _stop_realtime()
        _decisions_view(client, executions)
    elif nav == "Projekter":
        _stop_realtime()
        _projects_view(client, projects)
    elif nav == "Execution":
        _execution_view(client)
    elif nav == "Evidens":
        _stop_realtime()
        _evidence_view(client)
    elif nav == "Governance":
        _stop_realtime()
        _governance_view(client)
    elif nav == "Integration":
        _stop_realtime()
        _integration_view(client)


if __name__ == "__main__":
    main()
