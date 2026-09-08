"""DOR Control Plane operator-center GUI.

Presentation is intentionally thin: all business state, authorization and
state transitions are owned by the authenticated FastAPI API.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.context_navigation import render_sidebar_organization_switcher, sync_organization_context
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration
from dashboard.state import authenticated, clear_auth, init_state
from dashboard.ui_primitives import format_timestamp

st.set_page_config(page_title="DOR / Guide", page_icon="D", layout="wide", initial_sidebar_state="expanded")
init_state()


def api() -> DORAPIClient:
    return DORAPIClient(token=st.session_state.get("access_token"))


def css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background:#f7f5ee; color:#18313a; }
        [data-testid="stSidebar"] { background:#153039; }
        [data-testid="stSidebar"] * { color:#eef5f2 !important; }
        .hero { padding:8px 0 18px; }
        .eyebrow { color:#71878b; font-size:.72rem; letter-spacing:.12em; text-transform:uppercase; font-weight:700; }
        .hero h1 { margin:.2rem 0 .35rem; color:#17333c; font-size:2rem; }
        .muted { color:#708589; }
        .card { background:#fbfaf5; border:1px solid #dce2dc; border-radius:16px; padding:18px; min-height:112px; box-shadow:0 1px 2px rgba(20,40,45,.03); }
        .card-title { color:#708589; font-size:.76rem; font-weight:700; letter-spacing:.02em; }
        .card-value { color:#18313a; font-size:1.65rem; font-weight:750; margin-top:10px; }
        .card-foot { color:#7b8f92; font-size:.72rem; margin-top:6px; }
        .project-card { background:#fbfaf5; border:1px solid #d7dfd8; border-radius:18px; padding:22px; }
        .pill { display:inline-block; padding:5px 10px; border-radius:999px; background:#f2ded8; color:#a95748; font-size:.72rem; font-weight:700; }
        .step { text-align:center; color:#71878b; font-size:.72rem; font-weight:650; }
        .step-dot { width:28px; height:28px; border-radius:50%; border:1px solid #cddbd6; margin:0 auto 7px; display:flex; align-items:center; justify-content:center; background:#f7f9f5; }
        .step-done .step-dot { background:#2c8877; border-color:#2c8877; color:white; }
        .step-current .step-dot { background:#f7e1db; border:2px solid #df7867; color:#17333c; }
        .action { background:#eef5f0; border-radius:14px; padding:16px; }
        .action h4 { margin:0 0 5px; color:#315c62; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def login() -> None:
    st.markdown('<div class="hero"><div class="eyebrow">DIGITAL ORGANIZATION RUNTIME</div><h1>DOR / Guide</h1><div class="muted">Operatørcenter for det API-styrede DOR Control Plane.</div></div>', unsafe_allow_html=True)
    with st.form("login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submit = st.form_submit_button("Log ind", type="primary")
    if submit:
        try:
            client = DORAPIClient()
            token = client.login(username, password)
            st.session_state["access_token"] = token
            st.session_state["username"] = username
            st.rerun()
        except DORAPIError as exc:
            st.error(f"Login fejlede ({exc.status_code}): {exc}")


def _safe_get(client: DORAPIClient, path: str, **kwargs: Any) -> Any:
    try:
        return client.get(path, **kwargs)
    except DORAPIError as exc:
        if exc.status_code == 401:
            clear_auth()
            st.rerun()
        return None


def _projects(client: DORAPIClient, organization_id: str) -> list[dict[str, Any]]:
    payload = _safe_get(client, "/api/v1/control-plane/projects", params={"organization_id": organization_id})
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("projects")
    return [dict(x) for x in raw if isinstance(x, Mapping)] if isinstance(raw, list) else []


def _executions(client: DORAPIClient) -> list[dict[str, Any]]:
    payload = _safe_get(client, "/api/v1/execution")
    return [dict(x) for x in payload if isinstance(x, Mapping)] if isinstance(payload, list) else []


def _stage(state: str) -> int:
    value = state.lower()
    if any(x in value for x in ("idea", "intent", "onboard")):
        return 0
    if any(x in value for x in ("plan", "requirement", "audit")):
        return 1
    if any(x in value for x in ("implement", "build", "work", "test", "execute")):
        return 2
    if any(x in value for x in ("decision", "gate", "approval", "review")):
        return 3
    if any(x in value for x in ("deliver", "release", "certif")):
        return 4
    return 2


def _next_action(execution: Mapping[str, Any] | None) -> str:
    if not execution:
        return "Vælg et projekt for at se næste backend-ejede handling."
    action = str(execution.get("action_required") or "none")
    return {
        "human_decision": "Læs beslutningssporet og verificér, at anbefalingen matcher kravene.",
        "rejected": "Gennemgå den afviste gate og vælg backend-godkendt rework eller retry.",
        "rework_active": "Overvåg det aktive rework; gaten forbliver blocking indtil backend åbner den.",
        "work_in_progress": "Lad execution fortsætte og følg dens evidens og gates.",
        "terminal": "Gennemgå leveringsbeviset og den afsluttede evidenskæde.",
    }.get(action, "Ingen human handling kræves lige nu.")


def _metric(title: str, value: str | int, foot: str) -> None:
    st.markdown(f'<div class="card"><div class="card-title">{title}</div><div class="card-value">{value}</div><div class="card-foot">{foot}</div></div>', unsafe_allow_html=True)


def _workflow_for_project(executions: list[dict[str, Any]], project_id: str | None) -> dict[str, Any] | None:
    candidates = [x for x in executions if project_id and x.get("project_id") == project_id]
    if not candidates:
        candidates = [x for x in executions if not x.get("terminal")]
    return candidates[0] if candidates else (executions[0] if executions else None)


def overview(client: DORAPIClient, projects: list[dict[str, Any]], executions: list[dict[str, Any]]) -> None:
    active = [x for x in executions if not x.get("terminal")]
    attention = [x for x in active if x.get("action_required") in {"human_decision", "rejected"}]
    completed = [x for x in executions if x.get("terminal")]
    selected_id = st.session_state.get("selected_project_id")
    selected = next((p for p in projects if p.get("project_id") == selected_id), None)
    if selected is None and projects:
        selected = projects[0]
        st.session_state["selected_project_id"] = selected.get("project_id")
    execution = _workflow_for_project(executions, selected.get("project_id") if selected else None)

    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / OVERBLIK</div><h1>Godmorgen, ' + str(st.session_state.get("username") or "operatør") + '</h1><div class="muted">Her er det, der kræver, at du bliver først.</div></div>', unsafe_allow_html=True)
    cols = st.columns(4)
    with cols[0]: _metric("Aktive executions", len(active), f"{len(projects)} projekter i aktiv organisation")
    with cols[1]: _metric("Åbne beslutninger", len(attention), "Backend-ejede blocking states")
    with cols[2]: _metric("Gennemløb", len(executions), f"{len(completed)} afsluttede executions")
    with cols[3]: _metric("Blocking", sum(bool(x.get("blocking_gate")) for x in active), "Gates der holder progression tilbage")

    st.write("")
    left, right = st.columns([2.15, 1])
    with left:
        if selected and execution:
            st.markdown('<div class="project-card">', unsafe_allow_html=True)
            action = str(execution.get("action_required") or "none")
            if action in {"human_decision", "rejected"}:
                st.markdown('<span class="pill">Kræver menneske</span>', unsafe_allow_html=True)
            st.markdown(f"### {selected.get('name', 'Projekt')}")
            st.caption(f"Projekt · {selected.get('status', 'unknown')} · Workflow `{execution.get('workflow_id','—')}`")
            current = _stage(str(execution.get("current_state") or "unknown"))
            labels = ["Idé", "Plan", "Arbejde", "Beslutning", "Levering"]
            step_cols = st.columns(5)
            for i, (col, label) in enumerate(zip(step_cols, labels, strict=True)):
                cls = "step-done" if i < current else ("step-current" if i == current else "")
                mark = "✓" if i < current else str(i + 1)
                with col:
                    st.markdown(f'<div class="step {cls}"><div class="step-dot">{mark}</div>{label}</div>', unsafe_allow_html=True)
            st.progress(min(1.0, max(0.0, (current + 1) / 5)))
            st.markdown('<div class="action"><h4>Operatørens næste</h4><div>' + _next_action(execution) + '</div></div>', unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Åbn projekt →", type="primary", use_container_width=True):
                    st.session_state["selected_project_id"] = selected.get("project_id")
                    st.switch_page("pages/03_Requirements_And_Plan.py")
            with b2:
                if st.button("Åbn execution", use_container_width=True):
                    st.session_state["selected_workflow_id"] = execution.get("workflow_id")
                    st.session_state["workflow_input"] = execution.get("workflow_id")
                    st.session_state["active_nav"] = "Execution"
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("Ingen aktiv projekt/execution er endnu tilgængelig i backend.")

    with right:
        st.markdown('<div class="card"><div class="eyebrow">SYSTEMHELDBRED</div><h3>Rolig drift</h3>', unsafe_allow_html=True)
        readiness = _safe_get(client, "/health/ready")
        status = "READY" if isinstance(readiness, Mapping) and readiness.get("status") == "ready" else "CHECK"
        st.metric("API / database", status)
        ops = _safe_get(client, "/api/v1/swarm/ops/health")
        if isinstance(ops, Mapping):
            for name, value in ops.items():
                if isinstance(value, Mapping):
                    st.caption(f"{name}: {value.get('status', 'unknown')}")
                else:
                    st.caption(f"{name}: {value}")
        st.caption("Senest kontrolleret via backend health endpoints.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.subheader("Seneste hændelser")
    rows = []
    for item in executions[:8]:
        rows.append({"Projekt": item.get("project_name", "—"), "State": item.get("current_state", "—"), "Handling": item.get("action_required", "none"), "Opdateret": format_timestamp(item.get("updated_at"))})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen execution-hændelser rapporteret af API'et.")


def decisions(client: DORAPIClient, executions: list[dict[str, Any]]) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / BESLUTNINGER</div><h1>Beslutninger</h1><div class="muted">Kun backend-ejede gates kan åbnes eller afgøres her.</div></div>', unsafe_allow_html=True)
    candidates = [x for x in executions if x.get("action_required") in {"human_decision", "rejected"}]
    if not candidates:
        st.success("Ingen åbne beslutninger kræver menneskelig handling.")
        return
    for item in candidates:
        with st.container(border=True):
            st.markdown(f"### {item.get('project_name','—')}")
            st.caption(f"Workflow `{item.get('workflow_id','—')}` · state `{item.get('current_state','—')}`")
            gate = item.get("blocking_gate") or {}
            st.warning(f"Blocking gate: `{gate.get('gate_id','—')}` · decision `{gate.get('decision','pending')}`")
            if st.button("Åbn execution-gates", key=f"decision-open-{item.get('workflow_id')}", type="primary"):
                st.session_state["selected_workflow_id"] = item.get("workflow_id")
                st.session_state["workflow_input"] = item.get("workflow_id")
                st.session_state["active_nav"] = "Execution"
                st.rerun()


def projects(client: DORAPIClient, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / PROJEKTER</div><h1>Projekter</h1><div class="muted">Projektdata kommer direkte fra Control Plane API.</div></div>', unsafe_allow_html=True)
    if projects:
        st.dataframe(projects, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen projekter i den aktive organisation.")
    st.subheader("Nyt projekt")
    with st.form("new-project"):
        name = st.text_input("Navn")
        goal = st.text_area("Mål")
        description = st.text_area("Beskrivelse")
        priority = st.selectbox("Prioritet", ["low", "medium", "high", "critical"], index=1)
        create = st.form_submit_button("Opret projekt", type="primary")
    if create:
        org = st.session_state.get("organization_id")
        if not org or not name.strip() or not goal.strip():
            st.warning("Organisation, navn og mål er påkrævet.")
            return
        try:
            result = client.post("/api/v1/control-plane/projects", json={"organization_id": org, "name": name.strip(), "command_id": f"gui-{__import__('uuid').uuid4()}", "intent": {"goal": goal.strip(), "description": description.strip(), "priority": priority, "constraints": {}, "required_capabilities": []}})
            project = result.get("project", result)
            st.session_state["selected_project_id"] = project.get("project_id")
            st.success("Projekt oprettet via Control Plane API.")
            st.rerun()
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")


def evidence(client: DORAPIClient) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / EVIDENS</div><h1>Evidens</h1><div class="muted">Read-only visning af durable, tenant-scoped evidence.</div></div>', unsafe_allow_html=True)
    evidence_type = st.selectbox("Evidenstype", ["evaluations", "observations", "snapshots", "work-packages", "candidates", "candidate-selections", "integration-plans", "integration-receipts"])
    identity = st.text_input("Evidence ID / plan fingerprint")
    if st.button("Hent evidens", type="primary"):
        if not identity.strip():
            st.warning("Evidence ID er påkrævet.")
            return
        try:
            result = client.get(f"/api/v1/bot-evidence/{evidence_type}/{identity.strip()}", params={"organization_id": st.session_state.get("organization_id")})
            st.success("Evidens hentet fra API.")
            st.json(result)
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")
    st.caption("Denne surface ændrer ikke evidens eller historik.")


def execution(client: DORAPIClient) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">OPERATØRCENTER / EXECUTION</div><h1>Execution & Decision Cockpit</h1><div class="muted">Realtime og workflow-state forbliver backend authority.</div></div>', unsafe_allow_html=True)
    workflow_id = st.text_input("Workflow ID", value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id.strip():
        st.info("Vælg en execution fra Overblik eller angiv et Workflow ID.")
        return
    workflow_id = workflow_id.strip()
    st.session_state["selected_workflow_id"] = workflow_id
    try:
        status = client.get(f"/api/v1/execution/{workflow_id}")
        st.json(status)
        gates_payload = client.get(f"/api/v1/execution/{workflow_id}/gates")
        gates = gates_payload if isinstance(gates_payload, list) else gates_payload.get("gates", []) if isinstance(gates_payload, Mapping) else []
        st.subheader("Quality Gates")
        for gate in gates:
            if not isinstance(gate, Mapping):
                continue
            gid = str(gate.get("id") or gate.get("gate_id") or "")
            decision = str(gate.get("decision") or gate.get("status") or "pending")
            with st.container(border=True):
                st.markdown(f"### {gate.get('name', gid)}")
                st.caption(f"Gate `{gid}` · status `{decision}`")
                if decision.lower() in {"pending", "human_required", "proposed"}:
                    a, b = st.columns(2)
                    with a:
                        if st.button("Godkend", key=f"approve-{workflow_id}-{gid}", type="primary"):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json={"gate_id": gid, "decision": "approved"})
                                st.success("Godkendelse accepteret af Execution API.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Gate afvist ({exc.status_code}): {exc}")
                    with b:
                        if st.button("Afvis", key=f"reject-{workflow_id}-{gid}"):
                            try:
                                client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json={"gate_id": gid, "decision": "rejected"})
                                st.warning("Gate afvist; workflowet forbliver fail-closed.")
                                st.rerun()
                            except DORAPIError as exc:
                                st.error(f"Gate afvist ({exc.status_code}): {exc}")
        if st.button("Advance workflow", type="primary"):
            try:
                client.post(f"/api/v1/execution/{workflow_id}/advance", json={"reason": "operator-center"})
                st.success("Advance accepteret af backend.")
                st.rerun()
            except DORAPIError as exc:
                st.error(f"Advance afvist ({exc.status_code}): {exc}")
    except DORAPIError as exc:
        st.error(f"Execution API-fejl ({exc.status_code}): {exc}")


def main() -> None:
    css()
    if not authenticated():
        login()
        return
    client = api()
    try:
        sync_organization_context(client)
        render_sidebar_organization_switcher(client)
    except DORAPIError as exc:
        if exc.status_code == 401:
            clear_auth()
            st.rerun()
        st.warning(f"Organisationer kunne ikke indlæses ({exc.status_code}): {exc}")

    org = st.session_state.get("organization_id")
    projects_data = _projects(client, org) if org else []
    executions_data = _executions(client)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### DOR / Guide")
    nav = st.sidebar.radio("", ["Overblik", "Beslutninger", "Projekter", "Execution", "Evidens", "Governance", "Integration"], key="active_nav")
    st.sidebar.caption(f"Bruger: {st.session_state.get('username') or '—'}")
    if st.sidebar.button("Log ud"):
        clear_auth()
        st.rerun()

    if nav == "Overblik":
        overview(client, projects_data, executions_data)
    elif nav == "Beslutninger":
        decisions(client, executions_data)
    elif nav == "Projekter":
        projects(client, projects_data)
    elif nav == "Execution":
        execution(client)
    elif nav == "Evidens":
        evidence(client)
    elif nav == "Governance":
        render_multi_bot_control_plane(client, org or "")
    else:
        render_redmine_integration(client)


if __name__ == "__main__":
    main()
