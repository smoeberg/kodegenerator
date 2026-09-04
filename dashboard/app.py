"""DOR Control Plane GUI.

Three business logics, one live FastAPI source of truth:
1. Project initiation / requirements
2. Development / execution control
3. System administration / governance
"""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.state import authenticated, clear_auth, init_state

st.set_page_config(page_title="DOR Control Plane", page_icon="⚡", layout="wide")
init_state()


def api() -> DORAPIClient:
    return DORAPIClient(token=st.session_state.get("access_token"))


def login() -> None:
    st.title("⚡ DOR Control Plane")
    st.caption("Live Streamlit-klient til FastAPI på DOR_API_URL / http://api:8000")
    with st.form("login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submit = st.form_submit_button("Log ind", type="primary")
    if submit:
        try:
            token = DORAPIClient().login(username, password)
            st.session_state["access_token"] = token
            st.session_state["username"] = username
            st.rerun()
        except DORAPIError as exc:
            st.error(f"Login fejlede ({exc.status_code}): {exc}")


def global_header(client: DORAPIClient) -> None:
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
        clear_auth()
        st.rerun()


def project_page(client: DORAPIClient) -> None:
    st.header("🏗️ Projekt & Krav")
    st.write("**Hvad bygger vi?** Definér projektets immutable intent før udvikling.")
    with st.form("project_create"):
        goal = st.text_area("Mål", height=100)
        description = st.text_area("Beskrivelse", height=100)
        priority = st.selectbox("Prioritet", ["low", "medium", "high", "critical"], index=1)
        constraints = st.text_area("Begrænsninger", help="Én pr. linje")
        capabilities = st.text_area("Påkrævede capabilities", help="Én pr. linje")
        organization_id = st.text_input("Organisation ID", value=st.session_state.get("organization_id") or "")
        create = st.form_submit_button("Opret immutable projekt", type="primary")
    if create:
        if not goal.strip() or not organization_id.strip():
            st.warning("Mål og organisation ID er påkrævet.")
            return
        payload = {"organization_id": organization_id.strip(), "goal": goal.strip(), "description": description.strip(), "priority": priority, "constraints": [x.strip() for x in constraints.splitlines() if x.strip()], "required_capabilities": [x.strip() for x in capabilities.splitlines() if x.strip()]}
        try:
            result = client.post("/api/v1/control-plane/projects", json=payload)
            st.session_state["organization_id"] = organization_id.strip()
            st.session_state["selected_project_id"] = result.get("id") or result.get("project_id")
            st.success("Projekt oprettet.")
            st.json(result)
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")

    project_id = st.text_input("Eksisterende projekt ID", value=st.session_state.get("selected_project_id") or "")
    if project_id:
        st.session_state["selected_project_id"] = project_id
        try:
            st.subheader("Projekt")
            st.json(client.get(f"/api/v1/control-plane/projects/{project_id}"))
            if st.button("🚀 Request launch", type="primary"):
                confirm = st.checkbox("Jeg bekræfter launch-operationen", key="confirm_launch")
                if confirm:
                    st.json(client.post(f"/api/v1/control-plane/projects/{project_id}/launch", json={}))
                else:
                    st.warning("Bekræft launch først.")
        except DORAPIError as exc:
            st.warning(f"Projekt kunne ikke hentes ({exc.status_code}): {exc}")


def development_page(client: DORAPIClient) -> None:
    st.header("⚙️ Udvikling & Eksekvering")
    st.write("**Hvordan bygger vi?** Workflow → pipeline → gates → beslutninger → execution.")
    project_id = st.text_input("Projekt ID", value=st.session_state.get("selected_project_id") or "")
    if project_id:
        st.session_state["selected_project_id"] = project_id
        try:
            st.json(client.get(f"/api/v1/control-plane/projects/{project_id}"))
        except DORAPIError as exc:
            st.warning(str(exc))
    st.divider()
    workflow_id = st.text_input("Workflow ID")
    if workflow_id:
        col1, col2 = st.columns(2)
        with col1:
            try:
                st.subheader("Workflow")
                st.json(client.get(f"/workflows/{workflow_id}"))
            except DORAPIError as exc:
                st.warning(f"Workflow: {exc}")
        with col2:
            try:
                st.subheader("Pipeline")
                st.json(client.get(f"/pipeline/{workflow_id}"))
            except DORAPIError as exc:
                st.warning(f"Pipeline: {exc}")
    st.caption("Worker claim/heartbeat/complete er backend worker-protokol og eksponeres ikke som menneskeknapper.")


def administration_page(client: DORAPIClient) -> None:
    st.header("🛡️ Systemadministration")
    st.write("**Hvordan styres DOR?** Governance af profiles, roles, templates, connections, deployments og allocations.")
    st.info("Append-only: GUI'en viser ingen DELETE-operationer. Hvor API'et understøtter det, bruges disable.")
    paths = {"Profiles": "/api/v1/bot-governance/profiles", "Roles": "/api/v1/bot-governance/roles", "Templates": "/api/v1/bot-governance/templates", "Connections": "/api/v1/bot-governance/connections", "Deployments": "/api/v1/bot-governance/deployments", "Allocations": "/api/v1/bot-governance/allocations"}
    for label, path in paths.items():
        with st.expander(label):
            try:
                st.json(client.get(path))
            except DORAPIError as exc:
                st.caption(f"Ikke tilgængelig: {exc}")


def main() -> None:
    if not authenticated():
        login()
        return
    client = api()
    global_header(client)
    page = st.sidebar.radio("Kontrolplan", ["🏗️ Projekt & Krav", "⚙️ Udvikling & Eksekvering", "🛡️ Systemadministration"])
    try:
        if page.startswith("🏗️"):
            project_page(client)
        elif page.startswith("⚙️"):
            development_page(client)
        else:
            administration_page(client)
    except DORAPIError as exc:
        if exc.status_code == 401:
            clear_auth()
            st.warning("API-session udløbet. Log ind igen.")
            st.rerun()
        raise


if __name__ == "__main__":
    main()
