"""DOR Control Plane GUI: three business logics over the canonical FastAPI API."""
from __future__ import annotations

import uuid

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_view_model import (
    build_execution_summary,
    gate_decision_payload,
    interpret_advance_error,
    normalize_gates,
    normalize_proposals,
)
from dashboard.evidence_trace import render_evidence_trace
from dashboard.realtime import WorkflowRealtime
from dashboard.redmine_integration import render_redmine_integration
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
    st.header("⚙️ Logik 2: Udvikling & Decision Cockpit")
    st.write("**Hvordan bygger vi?** Realtime execution-status, Quality Gates (HITL) og kodeforslag fra den kanoniske Execution API.")

    workflow_id = st.text_input("Aktivt Workflow ID", value=st.session_state.get("selected_workflow_id") or "")
    if not workflow_id:
        stop_realtime()
        st.info("Angiv et Workflow ID for at aktivere realtids-cockpit og streams.")
        return

    workflow_id = workflow_id.strip()
    st.session_state["selected_workflow_id"] = workflow_id
    manager = ensure_realtime(workflow_id)
    realtime_pump(workflow_id)

    connection_cols = st.columns(4)
    connection_cols[0].metric("Realtime", manager.status)
    connection_cols[1].metric("Stream events", st.session_state.get("realtime_event_count", 0))
    connection_cols[2].metric("Seneste event", st.session_state.get("last_realtime_event", "—"))
    connection_cols[3].metric("Workflow", workflow_id)

    st.divider()
    st.subheader("📊 Workflowstatus")
    try:
        exec_status = client.get(f"/api/v1/execution/{workflow_id}")
        summary = build_execution_summary(exec_status)

        status_cols = st.columns(4)
        status_cols[0].metric("Projekt", summary["project_name"])
        status_cols[1].metric("Aktuel fase", summary["current_state"])
        status_cols[2].metric("Tasks færdige", f"{summary['task_completed']} / {summary['task_total']}")
        status_cols[3].metric("Åbne tasks", summary["task_open"])

        if summary["error"]:
            st.error(f"Execution-fejl: {summary['error']}")
        st.info(f"**Næste forventede handling:** {summary['next_action']}")

        if summary["tasks"]:
            st.dataframe(summary["tasks"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen tasks rapporteret af backend for denne execution.")

        advance_reason = st.text_input(
            "Reason for advance (valgfri)",
            key=f"advance_reason_{workflow_id}",
            help="Sendes til backend som audit-kontekst; backend afgør om workflowet må fortsætte.",
        )
        if st.button("⏩ Advance workflow", type="primary", key=f"advance_{workflow_id}"):
            try:
                payload = {"reason": advance_reason.strip() or None}
                adv = client.post(f"/api/v1/execution/{workflow_id}/advance", json=payload)
                st.success("Advance-kommando accepteret af Execution API.")
                with st.expander("Backend-resultat"):
                    st.json(adv)
                st.rerun()
            except DORAPIError as exc:
                error_state = interpret_advance_error(exc.status_code, str(exc))
                if error_state["kind"] == "gate_blocked":
                    st.warning(error_state["message"])
                else:
                    st.error(f"Advance afvist ({exc.status_code}): {error_state['message']}")

        with st.expander("Tekniske execution-data"):
            st.json(exec_status)
    except DORAPIError as exc:
        if exc.status_code == 401:
            stop_realtime()
            clear_auth()
            st.warning("API-session udløbet. Log ind igen.")
            st.rerun()
        st.warning(f"Execution API: {exc}")

    st.divider()
    st.subheader("🛡️ Quality Gates & Human-In-The-Loop")
    try:
        gates_payload = client.get(f"/api/v1/execution/{workflow_id}/gates")
        gates = normalize_gates(gates_payload)
        unresolved = [gate for gate in gates if gate["status"] == "human_required"]
        rejected = [gate for gate in gates if gate["status"] == "rejected"]
        blocking = [gate for gate in gates if gate["blocking"]]

        gate_cols = st.columns(4)
        gate_cols[0].metric("Quality gates", len(gates))
        gate_cols[1].metric("Kræver beslutning", len(unresolved))
        gate_cols[2].metric("Afvist", len(rejected))
        gate_cols[3].metric("Blocking", len(blocking))

        if blocking:
            blocking_ids = ", ".join(gate["id"] for gate in blocking)
            st.error(
                "Workflowet er blokeret af quality gate(s): "
                f"{blocking_ids}. Backend er eneste authority for videre progression."
            )

        if not gates:
            st.caption("Ingen quality gates rapporteret af backend.")

        for gate in gates:
            if gate["status"] == "rejected":
                icon = "🛑"
                status_label = "REJECTED / BLOCKING" if gate["blocking"] else "REJECTED"
            elif gate["status"] == "approved":
                icon = "✅"
                status_label = "APPROVED"
            elif gate["status"] == "resolved":
                icon = "✅"
                status_label = "RESOLVED"
            else:
                icon = "⚠️"
                status_label = "HUMAN_REQUIRED"

            with st.container(border=True):
                st.markdown(f"### {icon} {gate['name']}")
                decision_label = gate["decision"] or "pending"
                st.caption(
                    f"Gate ID: `{gate['id']}` · Status: `{status_label}` · "
                    f"Decision: `{decision_label}`"
                )
                st.write(gate["description"])

                if gate["blocking"]:
                    st.error("Denne gate blokerer workflowets progression.")

                if not gate["can_decide"]:
                    if gate["status"] == "rejected":
                        st.warning(
                            "Gate er afvist. Workflowet forbliver fail-closed, indtil backend "
                            "tilbyder en eksplicit rework/retry-handling."
                        )
                    elif gate["status"] == "approved":
                        st.success("Gate er godkendt af backend.")
                    else:
                        st.info("Gate er allerede afgjort af backend.")
                    continue

                decision_cols = st.columns(2)
                if decision_cols[0].button(
                    "✅ Godkend gate",
                    type="primary",
                    key=f"approve_gate_{workflow_id}_{gate['id']}",
                ):
                    try:
                        payload = gate_decision_payload(gate["id"], "approved")
                        result = client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json=payload)
                        st.success("Gate blev godkendt af Execution API.")
                        with st.expander("Backend-resultat"):
                            st.json(result)
                        st.rerun()
                    except DORAPIError as exc:
                        st.error(f"Gate-beslutning afvist ({exc.status_code}): {exc}")

                if decision_cols[1].button(
                    "❌ Afvis gate",
                    key=f"reject_gate_{workflow_id}_{gate['id']}",
                    help="Registrerer rejected i Execution API. Backend holder workflowet fail-closed.",
                ):
                    try:
                        payload = gate_decision_payload(gate["id"], "rejected")
                        result = client.post(f"/api/v1/execution/{workflow_id}/gates/decide", json=payload)
                        st.warning("Gate blev afvist. Workflowet forbliver blokeret af backend.")
                        with st.expander("Backend-resultat"):
                            st.json(result)
                        st.rerun()
                    except DORAPIError as exc:
                        st.error(f"Gate-beslutning afvist ({exc.status_code}): {exc}")

        with st.expander("Tekniske gate-data"):
            st.json(gates_payload)
    except DORAPIError as exc:
        st.caption(f"Gates ikke tilgængelige: {exc}")

    st.divider()
    st.subheader("📝 Kodeforslag & Diffs")
    try:
        proposals_payload = client.get(f"/api/v1/execution/{workflow_id}/proposals")
        proposals = normalize_proposals(proposals_payload)

        if not proposals:
            st.caption("Ingen implementation proposals rapporteret af backend.")

        for proposal in proposals:
            with st.container(border=True):
                st.markdown(f"### {proposal['title']}")
                st.caption(
                    f"Proposal `{proposal['id']}` · status `{proposal['status']}` · "
                    f"oprettet af `{proposal['created_by']}` · {proposal['created_at']}"
                )
                if proposal["summary"]:
                    st.write(proposal["summary"])

                if not proposal["files"]:
                    st.caption("Forslaget indeholder ingen filer.")
                for file_item in proposal["files"]:
                    with st.expander(f"📄 {file_item['display_name']}"):
                        if file_item["diff"]:
                            st.code(file_item["diff"], language="diff")
                        else:
                            st.caption("Backend leverede ikke diff/patch for denne fil.")
                            st.json(file_item["raw"])

                with st.expander("Tekniske proposal-data"):
                    st.json(proposal["raw"])
    except DORAPIError as exc:
        st.caption(f"Kodeforslag ikke tilgængelige: {exc}")

    render_evidence_trace(client, workflow_id)


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
        render_redmine_integration(client)

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
