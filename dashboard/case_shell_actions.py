"""Contextual actions and specialist tools for the canonical DOR case shell.

All mutations are submitted to backend APIs. This module never grants authority;
it only renders actions that backend snapshots/gate payloads expose.
"""
from __future__ import annotations

from typing import Mapping
from uuid import uuid4

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_process_projection import AttentionState
from dashboard.case_workbench import CaseWorkbenchItem
from dashboard.cockpit_lifecycle import render_cockpit_lifecycle
from dashboard.cockpit_view_model import (
    build_evidence_trace,
    gate_decision_payload,
    gate_rework_payload,
    gate_retry_payload,
    normalize_gates,
)
from dashboard.evidence_trace import render_evidence_trace
from dashboard.project_lifecycle import render_project_lifecycle_console
from dashboard.realtime import WorkflowRealtime
from dashboard.ui_primitives import format_timestamp


def stop_realtime() -> None:
    manager = st.session_state.get("realtime_manager")
    if isinstance(manager, WorkflowRealtime):
        manager.stop()
    st.session_state["realtime_manager"] = None
    st.session_state["realtime_workflow_id"] = None
    st.session_state["realtime_status"] = "offline"


def ensure_realtime(client: DORAPIClient, workflow_id: str) -> WorkflowRealtime:
    manager = st.session_state.get("realtime_manager")
    if (
        st.session_state.get("realtime_workflow_id") != workflow_id
        or not isinstance(manager, WorkflowRealtime)
    ):
        if isinstance(manager, WorkflowRealtime):
            manager.stop()
        manager = WorkflowRealtime(client, workflow_id)
        st.session_state["realtime_manager"] = manager
        st.session_state["realtime_workflow_id"] = workflow_id
        manager.start()
    st.session_state["realtime_status"] = manager.status
    return manager


def pump_realtime() -> None:
    manager = st.session_state.get("realtime_manager")
    if not isinstance(manager, WorkflowRealtime):
        return
    events = manager.drain()
    st.session_state["realtime_status"] = manager.status
    if manager.status == "unauthorized":
        stop_realtime()
        return
    if events:
        st.session_state["last_realtime_event"] = events[-1].event_type
        st.session_state["realtime_event_count"] = (
            st.session_state.get("realtime_event_count", 0) + len(events)
        )


def create_case_form(client: DORAPIClient) -> None:
    with st.expander("Opret ny sag"):
        with st.form("create-case"):
            name = st.text_input("Navn")
            goal = st.text_area("Hvad skal sagen opnå?")
            description = st.text_area("Beskrivelse")
            priority = st.selectbox(
                "Prioritet", ["low", "medium", "high", "critical"], index=1
            )
            constraints = st.text_area(
                "Begrænsninger", help="Valgfrit. Én nøgle=værdi pr. linje."
            )
            capabilities = st.text_area(
                "Påkrævede capabilities", help="Valgfrit. Én pr. linje."
            )
            submit = st.form_submit_button("Opret sag", type="primary")

        if not submit:
            return
        organization_id = st.session_state.get("organization_id")
        if not organization_id or not name.strip() or not goal.strip():
            st.warning("Organisation, navn og mål er påkrævet.")
            return

        constraint_map: dict[str, str] = {}
        for line in constraints.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip():
                    constraint_map[key.strip()] = value.strip()

        try:
            result = client.post(
                "/api/v1/control-plane/projects",
                json={
                    "organization_id": organization_id,
                    "name": name.strip(),
                    "command_id": str(uuid4()),
                    "description": description.strip(),
                    "intent": {
                        "goal": goal.strip(),
                        "description": description.strip(),
                        "priority": priority,
                        "constraints": constraint_map,
                        "required_capabilities": list(
                            dict.fromkeys(
                                value.strip()
                                for value in capabilities.splitlines()
                                if value.strip()
                            )
                        ),
                    },
                },
            )
            project = result.get("project", result) if isinstance(result, Mapping) else {}
            st.session_state["selected_project_id"] = project.get("project_id")
            st.success("Sagen er oprettet gennem Control Plane API.")
            st.rerun()
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")


def render_gate_actions(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    execution = item.execution
    if not execution:
        st.info("Der er endnu ingen tilknyttet execution for sagen.")
        return
    workflow_id = str(execution.get("workflow_id") or "").strip()
    if not workflow_id:
        st.info("Execution mangler workflow-identitet.")
        return

    try:
        gates = normalize_gates(client.get(f"/api/v1/execution/{workflow_id}/gates"))
    except DORAPIError as exc:
        st.error(f"Handlinger kunne ikke hentes ({exc.status_code}).")
        return

    actionable = [gate for gate in gates if gate["status"] in {"human_required", "rejected"}]
    if not actionable:
        st.info("Backend har ikke åbnet en human gate på denne sag.")
        return

    for gate in actionable:
        with st.container(border=True):
            st.markdown(f"**{gate['name']}**")
            st.write(gate["description"])
            if gate["status"] == "human_required":
                approve_col, reject_col = st.columns(2)
                with approve_col:
                    if st.button(
                        "Godkend",
                        key=f"approve-{workflow_id}-{gate['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            client.post(
                                f"/api/v1/execution/{workflow_id}/gates/decide",
                                json=gate_decision_payload(gate["id"], "approved"),
                            )
                            st.success("Beslutningen er registreret.")
                            st.rerun()
                        except DORAPIError as exc:
                            st.error(f"Afvist ({exc.status_code}): {exc}")
                with reject_col:
                    if st.button(
                        "Bed om ændringer",
                        key=f"reject-{workflow_id}-{gate['id']}",
                        use_container_width=True,
                    ):
                        try:
                            client.post(
                                f"/api/v1/execution/{workflow_id}/gates/decide",
                                json=gate_decision_payload(gate["id"], "rejected"),
                            )
                            st.warning("Ændringsønsket er registreret; workflowet er fail-closed.")
                            st.rerun()
                        except DORAPIError as exc:
                            st.error(f"Afvist ({exc.status_code}): {exc}")
                continue

            st.warning("Sagen er blokeret af en afvist gate.")
            if gate["can_rework"]:
                reason = st.text_area(
                    "Hvad skal ændres?",
                    key=f"rework-reason-{workflow_id}-{gate['id']}",
                    max_chars=2000,
                )
                if st.button(
                    "Bed DOR om at rette",
                    key=f"rework-{workflow_id}-{gate['id']}",
                    type="primary",
                ):
                    try:
                        client.post(
                            f"/api/v1/execution/{workflow_id}/gates/rework",
                            json=gate_rework_payload(gate["id"], reason),
                        )
                        st.success("Governed rework er køet.")
                        st.rerun()
                    except DORAPIError as exc:
                        st.error(f"Rework afvist ({exc.status_code}): {exc}")
            if gate["can_retry"]:
                reason = st.text_area(
                    "Begrundelse for ny vurdering",
                    key=f"retry-reason-{workflow_id}-{gate['id']}",
                    max_chars=2000,
                )
                if st.button(
                    "Åbn for ny vurdering",
                    key=f"retry-{workflow_id}-{gate['id']}",
                ):
                    try:
                        client.post(
                            f"/api/v1/execution/{workflow_id}/gates/retry",
                            json=gate_retry_payload(gate["id"], reason),
                        )
                        st.success("Ny decision-round er åbnet af backend.")
                        st.rerun()
                    except DORAPIError as exc:
                        st.error(f"Retry afvist ({exc.status_code}): {exc}")


def render_evidence_summary(item: CaseWorkbenchItem) -> None:
    for value in item.projection.evidence_completed:
        st.markdown(f"✓ {value}")
    for value in item.projection.evidence_missing:
        st.markdown(f"○ {value}")
    if not item.projection.evidence_completed and not item.projection.evidence_missing:
        st.caption("Der er endnu ingen projiceret evidensstatus for sagen.")


def render_execution_detail(client: DORAPIClient, workflow_id: str) -> None:
    manager = ensure_realtime(client, workflow_id)
    pump_realtime()
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


def render_technical_case_details(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    projection = item.projection
    st.json(projection.technical_refs)
    st.caption("Tekniske identiteter er read-only her og bruges ikke som normal navigation.")

    workflow_id = str(projection.technical_refs.get("workflow_id") or "").strip()
    if workflow_id and st.button(
        "Åbn teknisk execution-visning",
        key=f"technical-execution-{projection.case_id}",
    ):
        st.session_state["technical_workflow_id"] = workflow_id
        st.rerun()

    if st.checkbox("Vis rå backend-snapshot", key=f"raw-case-{projection.case_id}"):
        st.json(projection.raw_backend)


def render_project_lifecycle_tools(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    organization_id = st.session_state.get("organization_id")
    if not organization_id:
        return
    if st.toggle(
        "Vis avancerede lifecycle-handlinger",
        key=f"lifecycle-tools-{item.projection.case_id}",
    ):
        st.caption("Backend genvaliderer alle lifecycle-mutationer mod det aktuelle snapshot.")
        render_project_lifecycle_console(client, organization_id, item.project)


def evidence_lookup(client: DORAPIClient) -> None:
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
    label = st.selectbox("Evidenstype", list(mapping), key="technical-evidence-type")
    identity = st.text_input("Evidence ID / fingerprint", key="technical-evidence-id")
    if not st.button("Hent teknisk evidens", key="technical-evidence-fetch"):
        return
    if not identity.strip():
        st.warning("Evidence ID er påkrævet i specialist-opslaget.")
        return
    try:
        result = client.get(
            f"/api/v1/bot-evidence/{mapping[label]}/{identity.strip()}",
            params={"organization_id": st.session_state.get("organization_id")},
        )
        st.json(result)
    except DORAPIError as exc:
        st.error(f"Evidence API ({exc.status_code}): {exc}")


def should_render_gate_actions(item: CaseWorkbenchItem) -> bool:
    return item.projection.attention_state in {
        AttentionState.NEEDS_DECISION,
        AttentionState.BLOCKED,
    }
