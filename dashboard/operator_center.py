"""Canonical DOR / Guide operator-center UI.

Presentation-only shell over the authenticated FastAPI Control Plane.
Workflow authority, authorization and persistence remain in the backend.
"""
from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_lifecycle import render_cockpit_lifecycle
from dashboard.cockpit_view_model import build_evidence_trace, gate_decision_payload, gate_rework_payload, gate_retry_payload, normalize_gates
from dashboard.context_navigation import render_sidebar_organization_switcher, sync_organization_context
from dashboard.evidence_trace import render_evidence_trace
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration
from dashboard.realtime import WorkflowRealtime
from dashboard.state import authenticated, clear_auth, init_state
from dashboard.ui_primitives import format_timestamp, status_badge

st.set_page_config(page_title="DOR / Guide", page_icon="D", layout="wide", initial_sidebar_state="expanded")
init_state()


def _theme() -> None:
    st.markdown("""
    <style>
    .stApp { background:#f7f5ee; color:#18313a; }
    [data-testid="stSidebar"] { background:#153039; }
    [data-testid="stSidebar"] * { color:#eef5f2 !important; }
    .hero { padding:8px 0 18px; }
    .eyebrow { color:#71878b; font-size:.70rem; letter-spacing:.14em; text-transform:uppercase; font-weight:750; }
    .hero h1 { margin:.18rem 0 .3rem; color:#17333c; font-size:2rem; }
    .muted { color:#708589; }
    .metric-card { background:#fbfaf5; border:1px solid #dce2dc; border-radius:16px; padding:17px; min-height:105px; }
    .metric-label { color:#71878b; font-size:.74rem; font-weight:700; }
    .metric-value { color:#18313a; font-size:1.62rem; font-weight:780; margin-top:10px; }
    .metric-foot { color:#7b8f92; font-size:.70rem; margin-top:5px; }
    .project-card { background:#fbfaf5; border:1px solid #d7dfd8; border-radius:18px; padding:22px; }
    .attention { background:#eef5f0; border-radius:14px; padding:15px 17px; }
    .pill { display:inline-block; padding:5px 10px; border-radius:999px; background:#f2ded8; color:#a95748; font-size:.70rem; font-weight:750; }
    .step { text-align:center; color:#71878b; font-size:.70rem; font-weight:700; }
    .dot { width:29px; height:29px; border-radius:50%; border:1px solid #cddbd6; margin:0 auto 7px; display:flex; align-items:center; justify-content:center; background:#f7f9f5; }
    .done .dot { background:#2c8877; border-color:#2c8877; color:white; }
    .current .dot { background:#f7e1db; border:2px solid #df7867; color:#17333c; }
    </style>
    """, unsafe_allow_html=True)


def api() -> DORAPIClient:
    return DORAPIClient(token=st.session_state.get("access_token"))


def _login() -> None:
    st.markdown('<div class="hero"><div class="eyebrow">DIGITAL ORGANIZATION RUNTIME</div><h1>DOR / Guide</h1><div class="muted">Operatørcenter for det API-styrede Control Plane.</div></div>', unsafe_allow_html=True)
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
        st.warning("API-session udløbet. Log ind igen.")
        st.rerun()
    if events:
        st.session_state["last_realtime_event"] = events[-1].event_type
        st.session_state["realtime_event_count"] = st.session_state.get("realtime_event_count", 0) + len(events)
        st.rerun()


def _metric(title: str, value: object, foot: str) -> None:
    st.markdown(f'<div class="metric-card"><div class="metric-label">{title}</div><div class="metric-value">{value}</div><div class="metric-foot">{foot}</div></div>', unsafe_allow_html=True)


def _get_projects(client: DORAPIClient, organization_id: str) -> list[dict[str, Any]]:
    payload = client.get("/api/v1/control-plane/projects", params={"organization_id": organization_id})
    raw = payload.get("projects", []) if isinstance(payload, Mapping) else []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _get_executions(client: DORAPIClient) -> list[dict[str, Any]]:
    payload = client.get("/api/v1/execution")
    return [dict(item) for item in payload if isinstance(item, Mapping)] if isinstance(payload, list) else []


def _stage(state: str) -> int:
    value = state.lower()
    if any(x in value for x in ("requirement", "analysis", "intent")): return 1
    if any(x in value for x in ("architecture", "contract", "generat", "implement", "build", "test", "execute")): return 2
    if any(x in value for x in ("gate", "review", "approval", "decision")): return 3
    if any(x in value for x in ("release", "deliver", "certif")): return 4
    return 0


def _overview(client: DORAPIClient, projects: list[dict[str, Any]], executions: list[dict[str, Any]]) -> None:
    active=[x for x in executions if not x.get("terminal")]
    attention=[x for x in active if x.get("action_required") in {"human_decision","rejected"}]
    blocking=[x for x in active if x.get("blocking_gate")]
    selected_id=st.session_state.get("selected_project_id")
    selected=next((p for p in projects if p.get("project_id")==selected_id),None)
    if selected is None and projects:
        selected=projects[0]; st.session_state["selected_project_id"]=selected.get("project_id")
    linked=[x for x in executions if selected and x.get("project_id")==selected.get("project_id")]
    execution=next(iter(linked),next(iter(active),None))
    st.markdown(f'<div class="hero"><div class="eyebrow">OPERATØRCENTER / OVERBLIK</div><h1>Godmorgen, {st.session_state.get("username") or "operatør"}</h1><div class="muted">Her er det, der kræver, at du bliver først.</div></div>',unsafe_allow_html=True)
    c=st.columns(4)
    with c[0]: _metric("Aktive executions",len(active),f"{len(projects)} projekter")
    with c[1]: _metric("Åbne beslutninger",len(attention),"Backend-ejede blocking states")
    with c[2]: _metric("Gennemløb",len(executions),f"{len(executions)-len(active)} afsluttede")
    with c[3]: _metric("Blocking",len(blocking),"Gates der holder progression tilbage")
    left,right=st.columns([2.15,1])
    with left:
        if selected and execution:
            st.markdown('<div class="project-card">',unsafe_allow_html=True)
            if execution.get("action_required") in {"human_decision","rejected"}: st.markdown('<span class="pill">Kræver menneske</span>',unsafe_allow_html=True)
            st.markdown(f"### {selected.get('name','Projekt')}")
            st.caption(f"Kundeprojekt · {selected.get('status','unknown')} · Workflow `{execution.get('workflow_id','—')}`")
            current=_stage(str(execution.get("current_state") or "")); labels=["Idé","Plan","Arbejde","Beslutning","Levering"]
            cols=st.columns(5)
            for i,(col,label) in enumerate(zip(cols,labels,strict=True)):
                cls="done" if i<current else ("current" if i==current else ""); mark="✓" if i<current else str(i+1)
                with col: st.markdown(f'<div class="step {cls}"><div class="dot">{mark}</div>{label}</div>',unsafe_allow_html=True)
            st.progress((current+1)/5)
            action=str(execution.get("action_required") or "none")
            text={"human_decision":"Læs beslutningssporet og verificér, at anbefalingen matcher kravene.","rejected":"Gennemgå afvisningen; brug kun backend-tilladt rework eller retry.","rework_active":"Governed rework kører. Afvent backend-resultatet.","work_in_progress":"Arbejde kører. Følg execution og evidens.","terminal":"Execution er afsluttet. Gennemgå leveringsbeviset."}.get(action,"Ingen human handling kræves lige nu.")
            st.markdown(f'<div class="attention"><b>Operatørens næste</b><br>{text}</div>',unsafe_allow_html=True)
            a,b=st.columns(2)
            with a:
                if st.button("Åbn projekt →",type="primary",use_container_width=True): st.session_state["active_nav"]="Projekter"; st.rerun()
            with b:
                if st.button("Åbn execution",use_container_width=True): st.session_state["selected_workflow_id"]=execution.get("workflow_id"); st.session_state["active_nav"]="Execution"; st.rerun()
            st.markdown('</div>',unsafe_allow_html=True)
        else: st.info("Ingen aktiv projekt/execution er rapporteret af backend.")
    with right:
        st.markdown('<div class="project-card"><div class="eyebrow">SYSTEMHELDBRED</div><h3>Rolig drift</h3>',unsafe_allow_html=True)
        try:
            ready=client.readiness(); state=ready.get("status","unknown") if isinstance(ready,Mapping) else "unknown"; st.metric("API / database",status_badge(state))
        except DORAPIError as exc: st.error(f"Readiness ({exc.status_code}): {exc}")
        try:
            ops=client.get("/api/v1/swarm/ops/health")
            if isinstance(ops,Mapping):
                for name,value in ops.items(): st.caption(f"{name}: {value.get('status',value) if isinstance(value,Mapping) else value}")
        except DORAPIError as exc: st.caption(f"Operations health ikke tilgængelig ({exc.status_code}).")
        st.caption("Status kommer direkte fra backend health surfaces."); st.markdown('</div>',unsafe_allow_html=True)
    st.subheader("Seneste hændelser")
    rows=[{"Projekt":x.get("project_name","—"),"State":x.get("current_state","—"),"Handling":x.get("action_required","none"),"Opdateret":format_timestamp(x.get("updated_at"))} for x in executions[:8]]
    if rows: st.dataframe(rows,use_container_width=True,hide_index=True)
    else: st.info("Ingen execution-hændelser rapporteret.")


def _projects_view(client: DORAPIClient, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / PROJEKTER</div><h1>Projekter</h1><div class="muted">Intent og launch håndteres af Control Plane API.</div></div>',unsafe_allow_html=True)
    for project in projects:
        with st.container(border=True):
            st.markdown(f"### {project.get('name',project.get('project_id'))}")
            st.caption(f"`{project.get('project_id')}` · {status_badge(project.get('status'))} · fingerprint `{str(project.get('project_fingerprint',''))[:16]}…`")
            intent=project.get("intent") if isinstance(project.get("intent"),Mapping) else {}
            st.write(project.get("description") or intent.get("goal","Ingen beskrivelse"))
            a,b=st.columns(2)
            with a:
                if st.button("Åbn",key=f"project-open-{project.get('project_id')}",type="primary"): st.session_state["selected_project_id"]=project.get("project_id"); st.rerun()
            with b:
                if project.get("status")=="created" and st.button("Request launch",key=f"project-launch-{project.get('project_id')}"):
                    try:
                        result=client.post(f"/api/v1/control-plane/projects/{project['project_id']}/launch",json={"organization_id":project["organization_id"],"command_id":str(uuid4()),"expected_project_fingerprint":project["project_fingerprint"]})
                        st.success("Launch request accepteret af Control Plane."); st.json(result)
                    except DORAPIError as exc: st.error(f"Launch afvist ({exc.status_code}): {exc}")
    if not projects: st.info("Ingen projekter i den aktive organisation.")
    with st.expander("Opret projekt"):
        with st.form("operator-create-project"):
            name=st.text_input("Navn"); goal=st.text_area("Mål"); description=st.text_area("Beskrivelse"); priority=st.selectbox("Prioritet",["low","medium","high","critical"],index=1); create=st.form_submit_button("Opret projekt",type="primary")
        if create:
            org=st.session_state.get("organization_id")
            if not org or not name.strip() or not goal.strip(): st.warning("Organisation, navn og mål er påkrævet.")
            else:
                try:
                    result=client.post("/api/v1/control-plane/projects",json={"organization_id":org,"name":name.strip(),"command_id":str(uuid4()),"description":description.strip(),"intent":{"goal":goal.strip(),"description":description.strip(),"priority":priority,"constraints":{},"required_capabilities":[]}})
                    st.success("Projekt oprettet gennem Control Plane API."); st.session_state["selected_project_id"]=result["project"]["project_id"]; st.rerun()
                except DORAPIError as exc: st.error(f"API-fejl ({exc.status_code}): {exc}")


def _decisions_view(client: DORAPIClient, executions: list[dict[str, Any]]) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / BESLUTNINGER</div><h1>Beslutninger</h1><div class="muted">Human-in-the-loop — kun backend-tilladte actions.</div></div>',unsafe_allow_html=True)
    candidates=[x for x in executions if x.get("action_required") in {"human_decision","rejected"}]
    if not candidates: st.success("Ingen åbne beslutninger kræver menneskelig handling."); return
    for item in candidates:
        workflow_id=str(item["workflow_id"])
        try: gates=normalize_gates(client.get(f"/api/v1/execution/{workflow_id}/gates"))
        except DORAPIError as exc: st.error(f"Gates kunne ikke hentes ({exc.status_code}): {exc}"); continue
        for gate in gates:
            if gate["status"] not in {"human_required","rejected"}: continue
            with st.container(border=True):
                st.markdown(f"### {status_badge(gate['status'],blocking=gate['blocking'])} · {gate['name']}")
                st.caption(f"Projekt {item.get('project_name','—')} · Workflow `{workflow_id}` · round `{gate['round']}`")
                st.write(gate["description"])
                if gate["status"]=="human_required":
                    a,b=st.columns(2)
                    with a:
                        if st.button("Godkend anbefaling",key=f"dec-approve-{workflow_id}-{gate['id']}",type="primary"):
                            try: client.post(f"/api/v1/execution/{workflow_id}/gates/decide",json=gate_decision_payload(gate["id"],"approved")); st.success("Beslutning registreret af backend."); st.rerun()
                            except DORAPIError as exc: st.error(f"Afvist ({exc.status_code}): {exc}")
                    with b:
                        if st.button("Afvis / bed om ændringer",key=f"dec-reject-{workflow_id}-{gate['id']}"):
                            try: client.post(f"/api/v1/execution/{workflow_id}/gates/decide",json=gate_decision_payload(gate["id"],"rejected")); st.warning("Afvisning registreret; workflowet er fail-closed."); st.rerun()
                            except DORAPIError as exc: st.error(f"Afvist ({exc.status_code}): {exc}")
                else:
                    st.warning("Gate er rejected og blocking.")
                    if gate["can_rework"]:
                        reason=st.text_area("Begrundelse for ændringer",key=f"rework-{workflow_id}-{gate['id']}",max_chars=2000)
                        if st.button("Bed om ændringer",key=f"rework-btn-{workflow_id}-{gate['id']}"):
                            try: client.post(f"/api/v1/execution/{workflow_id}/gates/rework",json=gate_rework_payload(gate["id"],reason)); st.success("Governed rework køet."); st.rerun()
                            except DORAPIError as exc: st.error(f"Rework afvist ({exc.status_code}): {exc}")
                    if gate["can_retry"]:
                        reason=st.text_area("Begrundelse for ny decision-round",key=f"retry-{workflow_id}-{gate['id']}",max_chars=2000)
                        if st.button("Åbn ny decision-round",key=f"retry-btn-{workflow_id}-{gate['id']}"):
                            try: client.post(f"/api/v1/execution/{workflow_id}/gates/retry",json=gate_retry_payload(gate["id"],reason)); st.success("Ny round åbnet af backend."); st.rerun()
                            except DORAPIError as exc: st.error(f"Retry afvist ({exc.status_code}): {exc}")


def _execution_view(client: DORAPIClient) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / EXECUTION</div><h1>Execution & Decision Cockpit</h1><div class="muted">Execution API er eneste authority for state transitions.</div></div>',unsafe_allow_html=True)
    workflow_id=st.text_input("Workflow ID",value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id: st.info("Vælg en execution fra Overblik eller angiv et Workflow ID."); return
    workflow_id=workflow_id.strip(); st.session_state["selected_workflow_id"]=workflow_id
    manager=_ensure_realtime(workflow_id); _realtime_pump(workflow_id)
    a,b,c=st.columns(3); a.metric("Realtime",status_badge(manager.status)); b.metric("Events",st.session_state.get("realtime_event_count",0)); c.metric("Seneste event",st.session_state.get("last_realtime_event","—"))
    render_cockpit_lifecycle(client,workflow_id)
    try:
        payload=client.get(f"/api/v1/execution/{workflow_id}")
        if isinstance(payload,Mapping):
            with st.expander("Tasks"): st.dataframe(payload.get("tasks",[]),use_container_width=True,hide_index=True)
        reason=st.text_input("Reason for advance",key=f"advance-reason-{workflow_id}")
        if st.button("Advance workflow",type="primary",key=f"advance-{workflow_id}"):
            try: result=client.post(f"/api/v1/execution/{workflow_id}/advance",json={"reason":reason.strip() or None}); st.success("Advance accepteret af backend."); st.json(result); st.rerun()
            except DORAPIError as exc: st.error(f"Advance afvist ({exc.status_code}): {exc}")
        with st.expander("Evidence Trace"):
            try:
                gates=client.get(f"/api/v1/execution/{workflow_id}/gates"); proposals=client.get(f"/api/v1/execution/{workflow_id}/proposals"); st.json(build_evidence_trace(payload,gates,proposals))
            except DORAPIError as exc: st.warning(f"Evidence trace ikke komplet ({exc.status_code}).")
    except DORAPIError as exc: st.error(f"Execution kunne ikke hentes ({exc.status_code}): {exc}")
    render_evidence_trace(client,workflow_id)


def _evidence_view(client: DORAPIClient) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / EVIDENS</div><h1>Evidens</h1><div class="muted">Read-only, tenant-scoped evidence fra API.</div></div>',unsafe_allow_html=True)
    mapping={"Evaluation":"evaluations","Observation":"observations","Snapshot":"snapshots","Work package":"work-packages","Candidate":"candidates","Candidate selection":"candidate-selections","Integration plan":"integration-plans","Integration receipt":"integration-receipts"}
    label=st.selectbox("Evidenstype",list(mapping)); identity=st.text_input("Evidence ID / fingerprint")
    if st.button("Hent evidens",type="primary"):
        if not identity.strip(): st.warning("Evidence ID er påkrævet."); return
        try: result=client.get(f"/api/v1/bot-evidence/{mapping[label]}/{identity.strip()}",params={"organization_id":st.session_state.get("organization_id")}); st.success("Evidens hentet."); st.json(result)
        except DORAPIError as exc: st.error(f"Evidence API ({exc.status_code}): {exc}")


def main() -> None:
    _theme()
    if not authenticated(): _stop_realtime(); _login(); return
    client=api()
    try:
        sync_organization_context(client); render_sidebar_organization_switcher(client)
    except DORAPIError as exc:
        if exc.status_code==401: clear_auth(); st.rerun()
        st.warning(f"Organisation context ({exc.status_code}): {exc}")
    org=st.session_state.get("organization_id")
    try: projects=_get_projects(client,org) if org else []
    except DORAPIError as exc: projects=[]; st.warning(f"Projektkatalog ({exc.status_code}): {exc}")
    try: executions=_get_executions(client)
    except DORAPIError as exc: executions=[]; st.warning(f"Execution-overblik ({exc.status_code}): {exc}")
    st.sidebar.markdown("### DOR / Guide")
    nav=st.sidebar.radio("",["Overblik","Beslutninger","Projekter","Execution","Evidens","Governance","Integration"],key="active_nav")
    st.sidebar.caption(f"Bruger: {st.session_state.get('username') or '—'}")
    if st.sidebar.button("Log ud"): _stop_realtime(); clear_auth(); st.rerun()
    if nav=="Overblik": _stop_realtime(); _overview(client,projects,executions)
    elif nav=="Beslutninger": _stop_realtime(); _decisions_view(client,executions)
    elif nav=="Projekter": _stop_realtime(); _projects_view(client,projects)
    elif nav=="Execution": _execution_view(client)
    elif nav=="Evidens": _stop_realtime(); _evidence_view(client)
    elif nav=="Governance": _stop_realtime(); render_multi_bot_control_plane(client,org or "") if org else st.warning("Vælg en organisation.")
    else: _stop_realtime(); render_redmine_integration(client)


if __name__ == "__main__": main()
