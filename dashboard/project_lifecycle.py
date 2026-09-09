"""GUI-101 project lifecycle projection over canonical Control Plane APIs.

This module is deliberately a thin client. It may decide which controls are useful
to display for a server-reported snapshot, but it never grants authority or infers
that a transition will succeed. Every mutation is bound to the exact server-owned
project fingerprint/revision/active-plan snapshot and the API remains fail-closed.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.ui_primitives import format_timestamp, status_badge

PROJECT_STATUSES = {
    "created",
    "launch_requested",
    "active",
    "completion_pending",
    "completed",
    "cancelled",
    "archived",
}


def lifecycle_affordances(project: Mapping[str, Any]) -> tuple[str, ...]:
    """Return UI affordances for a server-reported project snapshot.

    These are display hints only. The backend remains the authority for every
    transition and can reject any displayed action after a concurrent state change.
    """

    status = str(project.get("status") or "")
    if status == "created":
        return ("launch",)
    if status == "launch_requested":
        return ("activate_scope",)
    if status == "active":
        return ("activate_scope", "request_completion", "cancel")
    if status == "completion_pending":
        return ("complete", "cancel")
    if status == "completed":
        return ("archive", "continue")
    if status == "cancelled":
        return ("archive",)
    if status == "archived" and project.get("archived_from_status") == "completed":
        return ("continue",)
    return ()


def _required_text(project: Mapping[str, Any], field: str) -> str:
    value = project.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project snapshot is missing {field}")
    return value


def _revision(project: Mapping[str, Any]) -> int:
    value = project.get("revision")
    if type(value) is not int or value < 0:
        raise ValueError("project snapshot is missing a valid revision")
    return value


def _command_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("command_id is required")
    return value


def build_launch_payload(
    project: Mapping[str, Any], organization_id: str, command_id: str
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "expected_project_fingerprint": _required_text(project, "project_fingerprint"),
    }


def build_scope_activation_payload(
    project: Mapping[str, Any],
    organization_id: str,
    command_id: str,
    plan_request_fingerprint: str,
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "plan_request_fingerprint": plan_request_fingerprint.strip(),
        "expected_revision": _revision(project),
    }


def build_completion_request_payload(
    project: Mapping[str, Any], organization_id: str, command_id: str
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "expected_revision": _revision(project),
        "expected_plan_request_fingerprint": _required_text(
            project, "active_plan_request_fingerprint"
        ),
    }


def build_complete_payload(
    project: Mapping[str, Any],
    organization_id: str,
    command_id: str,
    evidence: Mapping[str, str],
) -> dict[str, Any]:
    payload = build_completion_request_payload(project, organization_id, command_id)
    payload["evidence"] = {
        "onboarding_intent_id": evidence["onboarding_intent_id"].strip(),
        "repository_commit_sha": evidence["repository_commit_sha"].strip(),
        "delivery_certificate_id": evidence["delivery_certificate_id"].strip(),
        "traceability_manifest_id": evidence["traceability_manifest_id"].strip(),
        "integration_receipt_id": evidence["integration_receipt_id"].strip(),
    }
    return payload


def build_cancel_payload(
    project: Mapping[str, Any], organization_id: str, command_id: str, reason: str
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "expected_revision": _revision(project),
        "reason": reason.strip(),
    }


def build_archive_payload(
    project: Mapping[str, Any], organization_id: str, command_id: str
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "expected_revision": _revision(project),
    }


def build_continue_payload(
    project: Mapping[str, Any],
    organization_id: str,
    command_id: str,
    *,
    name: str,
    description: str,
    intent: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "command_id": _command_id(command_id),
        "expected_source_revision": _revision(project),
        "name": name.strip(),
        "description": description.strip(),
        "intent": dict(intent),
    }


def lifecycle_error_message(status_code: int, detail: str) -> tuple[str, str]:
    """Translate transport failures without changing backend meaning."""

    if status_code == 401:
        return ("error", "API-sessionen er udløbet. Log ind igen.")
    if status_code == 403:
        return (
            "error",
            "Backend afviste lifecycle-handlingen pga. manglende autorisation. "
            "GUI'en kan ikke tilsidesætte afgørelsen.",
        )
    if status_code == 409:
        return (
            "warning",
            "Backend afviste lifecycle-handlingen. Projektets revision, aktive plan, "
            "evidence eller state kan have ændret sig. Hent projektet igen før et nyt forsøg.",
        )
    return ("error", f"Lifecycle-handlingen blev afvist ({status_code}): {detail}")


def _render_error(exc: DORAPIError) -> None:
    level, message = lifecycle_error_message(exc.status_code, str(exc))
    getattr(st, level)(message)
    with st.expander("Backend-fejl"):
        st.json(exc.payload if exc.payload is not None else {"detail": str(exc)})


def _post(
    client: DORAPIClient,
    path: str,
    payload: Mapping[str, Any],
    *,
    success_message: str,
) -> None:
    try:
        result = client.post(path, json=dict(payload))
    except DORAPIError as exc:
        _render_error(exc)
        return
    st.success(success_message)
    with st.expander("Backend-resultat"):
        st.json(result)
    st.rerun()


def _parse_constraints(value: str) -> dict[str, str]:
    constraints: dict[str, str] = {}
    for line in value.splitlines():
        if "=" not in line:
            continue
        key, item = line.split("=", 1)
        if key.strip():
            constraints[key.strip()] = item.strip()
    return constraints


def render_project_lifecycle_console(
    client: DORAPIClient,
    organization_id: str,
    project: Mapping[str, Any],
) -> None:
    """Render GUI-101 controls for one exact backend project snapshot."""

    project_id = _required_text(project, "project_id")
    status = str(project.get("status") or "")
    if status not in PROJECT_STATUSES:
        st.error("Backend returnerede en ukendt project lifecycle state.")
        return

    st.subheader("Project lifecycle")
    st.caption(
        "Backend er authority. Kontrollerne nedenfor er kun en command surface over "
        "det viste snapshot; alle mutationer genvalideres server-side."
    )
    cols = st.columns(4)
    cols[0].metric("Status", status_badge(status))
    cols[1].metric("Revision", _revision(project))
    cols[2].metric(
        "Aktiv plan",
        (project.get("active_plan_request_fingerprint") or "—")[:12],
    )
    cols[3].metric(
        "Opdateret",
        format_timestamp(project.get("updated_at")),
    )

    provenance = {
        "project_id": project_id,
        "organization_id": project.get("organization_id"),
        "revision": project.get("revision"),
        "active_plan_request_fingerprint": project.get(
            "active_plan_request_fingerprint"
        ),
        "completion_record_id": project.get("completion_record_id"),
        "cancellation_reason": project.get("cancellation_reason"),
        "archived_from_status": project.get("archived_from_status"),
        "continued_from_project_id": project.get("continued_from_project_id"),
    }
    with st.expander("Lifecycle provenance"):
        st.json(provenance)

    actions = lifecycle_affordances(project)
    if not actions:
        st.info("Der er ingen lifecycle-kommandoer at vise for dette backend-snapshot.")

    if "launch" in actions:
        with st.form(f"gui101_launch_{project_id}"):
            st.markdown("#### Request launch")
            st.caption("Kommandoen bindes til projektets immutable fingerprint.")
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            confirm = st.checkbox("Jeg bekræfter launch af dette viste project snapshot")
            submitted = st.form_submit_button("Request launch", type="primary")
        if submitted:
            if not confirm:
                st.warning("Bekræft launch før kommandoen sendes.")
            else:
                _post(
                    client,
                    f"/api/v1/control-plane/projects/{project_id}/launch",
                    build_launch_payload(project, organization_id, command_id),
                    success_message="Launch request accepteret af backend.",
                )

    if "activate_scope" in actions:
        with st.form(f"gui101_scope_{project_id}"):
            st.markdown("#### Aktivér scope")
            st.caption(
                "Den viste revision sendes som expected_revision. Et stale snapshot "
                "bliver afvist af backend."
            )
            plan = st.text_input("Plan request fingerprint (SHA-256)")
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            submitted = st.form_submit_button("Aktivér exact plan")
        if submitted:
            _post(
                client,
                f"/api/v1/control-plane/projects/{project_id}/scope/activate",
                build_scope_activation_payload(
                    project, organization_id, command_id, plan
                ),
                success_message="Scope activation accepteret af backend.",
            )

    if "request_completion" in actions:
        with st.form(f"gui101_completion_request_{project_id}"):
            st.markdown("#### Request completion")
            st.caption(
                "Requesten fryser ordinary work kun hvis backend fortsat ser den samme "
                "revision og aktive plan."
            )
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            confirm = st.checkbox(
                "Jeg bekræfter completion request for den viste aktive plan"
            )
            submitted = st.form_submit_button("Request completion", type="primary")
        if submitted:
            if not confirm:
                st.warning("Bekræft completion request før kommandoen sendes.")
            else:
                _post(
                    client,
                    f"/api/v1/control-plane/projects/{project_id}/completion/request",
                    build_completion_request_payload(
                        project, organization_id, command_id
                    ),
                    success_message="Completion request accepteret af backend.",
                )

    if "complete" in actions:
        with st.form(f"gui101_complete_{project_id}"):
            st.markdown("#### Verificér og complete")
            st.caption(
                "GUI'en erklærer aldrig projektet complete. Evidence sendes til backend, "
                "som genverificerer authoritative state umiddelbart før commit."
            )
            onboarding_intent_id = st.text_input("Onboarding intent ID")
            repository_commit_sha = st.text_input("Final repository commit SHA-1")
            delivery_certificate_id = st.text_input("Delivery certificate ID")
            traceability_manifest_id = st.text_input("Traceability manifest ID")
            integration_receipt_id = st.text_input("Integration receipt ID")
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            submitted = st.form_submit_button("Complete via backend", type="primary")
        if submitted:
            evidence = {
                "onboarding_intent_id": onboarding_intent_id,
                "repository_commit_sha": repository_commit_sha,
                "delivery_certificate_id": delivery_certificate_id,
                "traceability_manifest_id": traceability_manifest_id,
                "integration_receipt_id": integration_receipt_id,
            }
            _post(
                client,
                f"/api/v1/control-plane/projects/{project_id}/completion/complete",
                build_complete_payload(
                    project, organization_id, command_id, evidence
                ),
                success_message="Backend verificerede evidence og completed projektet.",
            )

    if "cancel" in actions:
        with st.form(f"gui101_cancel_{project_id}"):
            st.markdown("#### Cancel project")
            st.caption(
                "Cancellation betyder stoppet uden completion; den ruller ikke eksterne "
                "side effects tilbage."
            )
            reason = st.text_area("Cancellation reason")
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            confirm = st.checkbox("Jeg bekræfter cancellation uden completion")
            submitted = st.form_submit_button("Cancel project")
        if submitted:
            if not confirm or not reason.strip():
                st.warning("Cancellation kræver både bekræftelse og en reason.")
            else:
                _post(
                    client,
                    f"/api/v1/control-plane/projects/{project_id}/cancel",
                    build_cancel_payload(
                        project, organization_id, command_id, reason
                    ),
                    success_message="Project cancellation accepteret af backend.",
                )

    if "archive" in actions:
        with st.form(f"gui101_archive_{project_id}"):
            st.markdown("#### Archive project")
            st.caption(
                "Archive er kun catalog/storage state; terminal provenance bevares."
            )
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            confirm = st.checkbox("Jeg bekræfter archive af terminalt project")
            submitted = st.form_submit_button("Archive project")
        if submitted:
            if not confirm:
                st.warning("Bekræft archive før kommandoen sendes.")
            else:
                _post(
                    client,
                    f"/api/v1/control-plane/projects/{project_id}/archive",
                    build_archive_payload(project, organization_id, command_id),
                    success_message="Project archive accepteret af backend.",
                )

    if "continue" in actions:
        source_intent = project.get("intent")
        if not isinstance(source_intent, Mapping):
            source_intent = {}
        priority_options = ["low", "medium", "high", "critical"]
        source_priority = str(source_intent.get("priority") or "medium")
        priority_index = (
            priority_options.index(source_priority)
            if source_priority in priority_options
            else 1
        )
        source_constraints = source_intent.get("constraints")
        if not isinstance(source_constraints, Mapping):
            source_constraints = {}
        constraints_default = "\n".join(
            f"{key}={value}" for key, value in source_constraints.items()
        )
        source_capabilities = source_intent.get("required_capabilities")
        if not isinstance(source_capabilities, list):
            source_capabilities = []

        with st.form(f"gui101_continue_{project_id}"):
            st.markdown("#### Continue as new project")
            st.caption(
                "Continuation opretter en ny project identity; det terminale source project "
                "reopenes aldrig."
            )
            name = st.text_input(
                "New project name", value=f"{project.get('name', 'Project')} — continuation"
            )
            description = st.text_area(
                "Description", value=str(project.get("description") or "")
            )
            goal = st.text_area("Goal", value=str(source_intent.get("goal") or ""))
            intent_description = st.text_area(
                "Intent description",
                value=str(source_intent.get("description") or ""),
            )
            priority = st.selectbox(
                "Priority", priority_options, index=priority_index
            )
            constraints_text = st.text_area(
                "Constraints (key=value, one per line)", value=constraints_default
            )
            capabilities_text = st.text_area(
                "Required capabilities (one per line)",
                value="\n".join(str(item) for item in source_capabilities),
            )
            command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
            confirm = st.checkbox(
                "Jeg bekræfter, at dette skal være et nyt project med continuation lineage"
            )
            submitted = st.form_submit_button("Create continuation", type="primary")
        if submitted:
            if not confirm or not name.strip() or not goal.strip():
                st.warning("Continuation kræver bekræftelse, navn og goal.")
            else:
                intent = {
                    "goal": goal.strip(),
                    "description": intent_description.strip(),
                    "priority": priority,
                    "constraints": _parse_constraints(constraints_text),
                    "required_capabilities": list(
                        dict.fromkeys(
                            item.strip()
                            for item in capabilities_text.splitlines()
                            if item.strip()
                        )
                    ),
                }
                _post(
                    client,
                    f"/api/v1/control-plane/projects/{project_id}/continue",
                    build_continue_payload(
                        project,
                        organization_id,
                        command_id,
                        name=name,
                        description=description,
                        intent=intent,
                    ),
                    success_message="Backend oprettede et nyt continuation project.",
                )

    st.divider()
    if st.button("↻ Hent project events", key=f"gui101_events_{project_id}"):
        try:
            events = client.get(
                f"/api/v1/control-plane/projects/{project_id}/events",
                params={"organization_id": organization_id},
            )
        except DORAPIError as exc:
            _render_error(exc)
        else:
            with st.expander("Project events", expanded=True):
                st.json(events)
