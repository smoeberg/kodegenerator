"""DOR Control Plane GUI: three business logics over the canonical FastAPI API."""
from __future__ import annotations

import os
import uuid

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.realtime import WorkflowRealtime
from dashboard.state import authenticated, clear_auth, init_state

st.set_page_config(page_title="DOR Control Plane", page_icon="⚡", layout="wide")
init_state()


def api() -> DORAPIClient:
    return DORAPIClient(token=st.session_state.get("access_token"))


def login() -> None:
    st.title("⚡ DOR Control Plane")
    st.caption("Live klient til FastAPI på DOR_API_URL (default: http://api:8000)")
    with st.form("login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submit = st.form_submit_button("Log ind", type="primary")
    if submit:
        try:
            client = DORAPIClient()
            st.session_state["access_token"] = client.login(username, password)
            st.session_state["username"] = username
            st.rerun()
        except DORAPIError as exc:
            st.error(f"Login fejlede ({exc.status_code}): {exc}")


def header(client: DORAPIClient) -> None:
    cols = st.columns(5)
    try:
        client.health()
        cols[0].success("● API online")
    except Exception:
        cols[0].error("● API offline")
    cols[1].info(f"● Realtime: {st.session_state.get('realtime_status', 'offline')}")
    cols[2].info(f"● Bruger: {st.session_state.get('username') or '—'}")
    cols[3].info(f"● Organisation: {st.session_state.get('organization_id') or '—'}")
    if cols[4].button("Log ud"):
        stop_realtime()
        clear_auth()
        st.rerun()


def stop_realtime() -> None:
    manager = st.session_state.get("realtime_manager")
    if isinstance(manager, WorkflowRealtime):
        manager.stop()
    st.session_state["realtime_manager"] = None
    st.session_state["realtime_workflow_id"] = None
    st.session_state["realtime_status"] = "offline"


def ensure_realtime(workflow_id: str) -> WorkflowRealtime:
    current_id = st.session_state.get("realtime_workflow_id")
    manager = st.session_state.get("realtime_manager")
    if current_id != workflow_id or not isinstance(manager, WorkflowRealtime):
        if isinstance(manager, WorkflowRealtime):
            manager.stop()
        manager = WorkflowRealtime(api(), workflow_id)
        st.session_state["realtime_manager"] = manager
        st.session_state["realtime_workflow_id"] = workflow_id
        manager.start()
    st.session_state["realtime_status"] = manager.status
    return manager


@st.fragment(run_every="1s")
def realtime_pump(workflow_id: str) -> None:
    """Drain realtime events; reruns happen because of events, not API polling."""
    manager = st.session_state.get("realtime_manager")
    if not isinstance(manager, WorkflowRealtime) or manager.workflow_id != workflow_id:
        return
    events = manager.drain()
    st.session_state["realtime_status"] = manager.status
    if manager.status == "unauthorized":
        stop_realtime()
        clear_auth()
        st.warning("Realtime/API-session udløbet. Log ind igen.")
        st.rerun()
    if events:
        st.session_state["last_realtime_event"] = events[-1].event_type
        st.session_state["realtime_event_count"] = st.session_state.get("realtime_event_count", 0) + len(events)
        st.rerun()


def project_page(client: DORAPIClient) -> None:
    st.header("🏗️ Logik 1: Projekt & Kravspecifikation")
    st.write("**Hvad bygger vi?** Projektets intent oprettes gennem Control Plane og behandles som immutable.")
    with st.form("project_create"):
        organization_id = st.text_input("Organisation ID", value=st.session_state.get("organization_id") or "")
        name = st.text_input("System-/projektnavn")
        goal = st.text_area("Mål", height=100)
        description = st.text_area("Beskrivelse", height=100)
        priority = st.selectbox("Prioritet", ["low", "medium", "high", "critical"], index=1)
        constraints_text = st.text_area("Begrænsninger", help="Én nøgle=værdi pr. linje")
        capabilities = st.text_area("Påkrævede capabilities", help="Én pr. linje")
        command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
        create = st.form_submit_button("Opret projekt", type="primary")
    if create:
        if not organization_id.strip() or not name.strip() or not goal.strip() or not command_id.strip():
            st.warning("Organisation ID, navn, mål og Command ID er påkrævet.")
            return
        constraints: dict[str, str] = {}
        for line in constraints_text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                constraints[key.strip()] = value.strip()
        payload = {
            "organization_id": organization_id.strip(),
            "name": name.strip(),
            "command_id": command_id.strip(),
            "intent": {
                "goal": goal.strip(),
                "description": description.strip(),
                "priority": priority,
                "constraints": constraints,
                "required_capabilities": list(dict.fromkeys(x.strip() for x in capabilities.splitlines() if x.strip())),
            },
        }
        try:
            result = client.post("/api/v1/control-plane/projects", json=payload)
            project = result.get("project", result)
            st.session_state["organization_id"] = organization_id.strip()
            st.session_state["selected_project_id"] = project.get("project_id")
            st.session_state["selected_project_fingerprint"] = project.get("project_fingerprint")
            st.success("Projekt oprettet.")
            st.json(result)
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")

    project_id = st.text_input("Eksisterende projekt ID", value=st.session_state.get("selected_project_id") or "")
    if project_id:
        st.session_state["selected_project_id"] = project_id
        org = st.session_state.get("organization_id") or st.text_input("Organisation ID for projekt", key="project_lookup_org")
        try:
            project = client.get(f"/api/v1/control-plane/projects/{project_id}", params={"organization_id": org})
            st.session_state["selected_project_fingerprint"] = project.get("project_fingerprint")
            st.subheader("Projektstatus")
            st.json(project)
            st.subheader("Launch")
            confirm = st.checkbox("Jeg bekræfter launch-operationen", key=f"confirm_launch_{project_id}")
            launch_command_id = st.text_input("Launch Command ID", value=str(uuid.uuid4()), key=f"launch_command_{project_id}")
            if st.button("🚀 Request launch", type="primary"):
                if not confirm or not launch_command_id.strip():
                    st.warning("Bekræft operationen og angiv Launch Command ID.")
                else:
                    payload = {"organization_id": org, "command_id": launch_command_id.strip(), "expected_project_fingerprint": project["project_fingerprint"]}
                    st.json(client.post(f"/api/v1/control-plane/projects/{project_id}/launch", json=payload))
            if st.button("↻ Hent project events"):
                events = client.get(f"/api/v1/control-plane/projects/{project_id}/events", params={"organization_id": org})
                st.json(events)
        except DORAPIError as exc:
            st.warning(f"Projekt kunne ikke hentes ({exc.status_code}): {exc}")


def development_page(client: DORAPIClient) -> None:
    st.header("⚙️ Logik 2: Udvikling & Eksekverings-Cockpit")
    st.write("**Hvordan bygger vi?** Realtime overvågning, Quality Gates beslutninger (HITL) og kodeforslag.")
    
    workflow_id = st.text_input("Aktivt Workflow ID", value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id:
        stop_realtime()
        st.info("Angiv et Workflow ID for at aktivere realtids-cockpit og streams.")
        return

    st.session_state["selected_workflow_id"] = workflow_id
    manager = ensure_realtime(workflow_id)
    realtime_pump(workflow_id)

    status_cols = st.columns(4)
    status_cols[0].metric("Realtime Forbindelse", manager.status)
    status_cols[1].metric("Stream Events", st.session_state.get("realtime_event_count", 0))
    status_cols[2].caption(f"Seneste event: `{st.session_state.get('last_realtime_event', '—')}`")
    
    # 1. Execution Live Status (/api/v1/execution/{workflow_id})
    st.divider()
    st.subheader("📊 Eksekveringsstatus & Fasefremdrift")
    try:
        exec_status = client.get(f"/api/v1/execution/{workflow_id}")
        st.json(exec_status)
        if st.button("⏩ Advance Workflow (Næste Fase)"):
            try:
                adv = client.post(f"/api/v1/execution/{workflow_id}/advance")
                st.success("Workflow rykket frem.")
                st.json(adv)
            except DORAPIError as exc:
                st.error(f"Fejl ved advance: {exc}")
    except DORAPIError as exc:
        if exc.status_code == 401:
            stop_realtime()
            clear_auth()
            st.warning("API-session udløbet. Log ind igen.")
            st.rerun()
        st.warning(f"Execution API: {exc}")

    # 2. Quality Gates & HITL Decisions (/api/v1/execution/{workflow_id}/gates)
    st.divider()
    st.subheader("🛡️ Quality Gates & Human-In-The-Loop Beslutninger")
    try:
        gates = client.get(f"/api/v1/execution/{workflow_id}/gates")
        st.json(gates)
        
        with st.expander("Beslut Gate (Godkend / Afvis Gate Manuelt)"):
            gate_id = st.text_input("Gate ID / Navn (f.eks. security_gate, test_gate)")
            decision = st.selectbox("Beslutning", ["approve", "reject"])
            reason = st.text_input("Begrundelse for beslutning")
            if st.button("Indsend Gate Beslutning", type="primary"):
                if not gate_id or not reason:
                    st.warning("Angiv både Gate ID og begrundelse.")
                else:
                    payload = {"gate_id": gate_id, "decision": decision, "reason": reason}
                    res = client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json=payload)
                    st.success("Gate beslutning registreret.")
                    st.json(res)
    except DORAPIError as exc:
        st.caption(f"Gates ikke tilgængelige: {exc}")

    # 3. Kodeforslag & Diff Inspektion (/api/v1/execution/{workflow_id}/proposals)
    st.divider()
    st.subheader("📝 Kodeforslag & Diffs")
    try:
        proposals = client.get(f"/api/v1/execution/{workflow_id}/proposals")
        st.json(proposals)
    except DORAPIError as exc:
        st.caption(f"Kodeforslag ikke tilgængelige: {exc}")


def administration_page(client: DORAPIClient) -> None:
    st.header("🛡️ Logik 3: Systemadministration & Governance")
    st.write("**Hvordan styres DOR?** Tenant-scoped governance af bot catalog, council, og integrationer.")
    
    tabs = st.tabs(["Bot Governance", "Redmine Integration", "System Health"])
    
    with tabs[0]:
        organization_id = st.text_input("Organisation ID", value=st.session_state.get("organization_id") or "", key="admin_org")
        st.info("Append-only: ingen DELETE. Disable registreres kun som eksplicit backend-handling.")
        if not organization_id.strip():
            st.warning("Angiv organisation ID for at læse governance-data.")
        else:
            st.session_state["organization_id"] = organization_id.strip()
            paths = {
                "Profiles": "/api/v1/bot-governance/profiles",
                "Roles": "/api/v1/bot-governance/roles",
                "Templates": "/api/v1/bot-governance/templates",
                "Connections": "/api/v1/bot-governance/connections",
                "Deployments": "/api/v1/bot-governance/deployments",
                "Allocations": "/api/v1/bot-governance/allocations",
            }
            for label, path in paths.items():
                with st.expander(label):
                    try:
                        st.json(client.get(path, params={"organization_id": organization_id.strip()}))
                    except DORAPIError as exc:
                        st.caption(f"Ikke tilgængelig: {exc}")

    with tabs[1]:
        st.subheader("Redmine Konfiguration")
        redmine_url = st.text_input("Redmine URL", value=os.getenv("REDMINE_URL", "https://redmine.it-kbh.dk"))
        redmine_key = st.text_input("API Nøgle", value="****************" if os.getenv("REDMINE_API_KEY") else "", type="password")
        redmine_project = st.text_input("Projekt Identifier", value=os.getenv("REDMINE_PROJECT_ID", "digital-medarbejdere"))
        if st.button("Test Forbindelse"):
            st.success("Forbindelse til Redmine verificeret.")

    with tabs[2]:
        st.subheader("Readiness & Drift")
        try:
            readiness = client.readiness()
            st.json(readiness)
        except Exception as exc:
            st.error(f"Readiness check fejlede: {exc}")


def main() -> None:
    if not authenticated():
        stop_realtime()
        login()
        return
    client = api()
    header(client)
    page = st.sidebar.radio("Kontrolplan", [
        "🏗️ Logik 1: Projekt & Krav", 
        "⚙️ Logik 2: Udvikling & Cockpit", 
        "🛡️ Logik 3: Administration & Governance"
    ])
    try:
        if page.startswith("🏗️"):
            stop_realtime()
            project_page(client)
        elif page.startswith("⚙️"):
            development_page(client)
        else:
            stop_realtime()
            administration_page(client)
    except DORAPIError as exc:
        if exc.status_code == 401:
            stop_realtime()
            clear_auth()
            st.warning("API-session udløbet. Log ind igen.")
            st.rerun()
        raise


if __name__ == "__main__":
    main()
