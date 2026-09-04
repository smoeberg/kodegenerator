"""DOR Control Plane GUI: three business logics over the canonical FastAPI API."""
from __future__ import annotations

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
    cols[1].info(f"● Realtime: {st.session_state['realtime_status']}")
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
    st.header("🏗️ Projekt & Krav")
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
    st.header("⚙️ Udvikling & Eksekvering")
    st.write("**Hvordan bygger vi?** Workflow → pipeline → gates → decisions → execution.")
    project_id = st.text_input("Projekt ID", value=st.session_state.get("selected_project_id") or "")
    if project_id:
        org = st.session_state.get("organization_id") or st.text_input("Organisation ID", key="dev_org")
        try:
            st.json(client.get(f"/api/v1/control-plane/projects/{project_id}", params={"organization_id": org}))
        except DORAPIError as exc:
            st.warning(f"Projekt: {exc}")

    st.divider()
    workflow_id = st.text_input("Workflow ID", value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id:
        stop_realtime()
        st.info("Angiv et workflow ID for at aktivere workflow-scoped realtime.")
        return

    st.session_state["selected_workflow_id"] = workflow_id
    manager = ensure_realtime(workflow_id)
    realtime_pump(workflow_id)

    status_cols = st.columns(3)
    status_cols[0].metric("Realtime", manager.status)
    status_cols[1].metric("Events", st.session_state.get("realtime_event_count", 0))
    status_cols[2].caption(f"Seneste event: {st.session_state.get('last_realtime_event', '—')}")

    col1, col2 = st.columns(2)
    with col1:
        try:
            st.subheader("Workflow")
            st.json(client.get(f"/workflows/{workflow_id}"))
        except DORAPIError as exc:
            if exc.status_code == 401:
                stop_realtime()
                clear_auth()
                st.warning("API-session udløbet. Log ind igen.")
                st.rerun()
            st.warning(f"Workflow: {exc}")
    with col2:
        try:
            st.subheader("Pipeline")
            st.json(client.get(f"/pipeline/{workflow_id}"))
        except DORAPIError as exc:
            st.warning(f"Pipeline: {exc}")
    st.caption("Worker claim/heartbeat/complete er backend worker-protokol og vises ikke som menneskeknapper.")


def administration_page(client: DORAPIClient) -> None:
    st.header("🛡️ Systemadministration")
    st.write("**Hvordan styres DOR?** Tenant-scoped governance af bot catalog og council-konfiguration.")
    organization_id = st.text_input("Organisation ID", value=st.session_state.get("organization_id") or "", key="admin_org")
    st.info("Append-only: ingen DELETE. Disable vises kun som eksplicit backend-kommando, når relevant.")
    if not organization_id.strip():
        st.warning("Angiv organisation ID for at læse governance-data.")
        return
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


def main() -> None:
    if not authenticated():
        stop_realtime()
        login()
        return
    client = api()
    header(client)
    page = st.sidebar.radio("Kontrolplan", ["🏗️ Projekt & Krav", "⚙️ Udvikling & Eksekvering", "🛡️ Systemadministration"])
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
