"""Operator-facing read-only overview of canonical execution summaries."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_lifecycle import render_cockpit_lifecycle
from dashboard.context_navigation import render_context_navigation

_ACTION_PRIORITY = {
    "human_decision": 0,
    "rejected": 1,
    "rework_active": 2,
    "work_in_progress": 3,
    "none": 4,
    "terminal": 5,
}
_ACTION_LABELS = {
    "human_decision": "Kræver human beslutning",
    "rejected": "Afvist / blocking",
    "rework_active": "Rework kører",
    "work_in_progress": "Arbejde kører",
    "none": "Ingen human handling krævet",
    "terminal": "Afsluttet",
}


def normalize_execution_overview(payload: Any) -> list[dict[str, Any]]:
    """Normalize backend-owned execution summaries without inventing authority."""
    if not isinstance(payload, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        workflow_id = str(item.get("workflow_id") or "").strip()
        if not workflow_id:
            continue

        action = str(item.get("action_required") or "none").strip().lower()
        if action not in _ACTION_PRIORITY:
            action = "none"

        blocking_value = item.get("blocking_gate")
        blocking_gate = (
            dict(blocking_value) if isinstance(blocking_value, Mapping) else None
        )
        rework_value = item.get("rework")
        rework = dict(rework_value) if isinstance(rework_value, Mapping) else None

        try:
            task_total = max(0, int(item.get("task_total") or 0))
        except (TypeError, ValueError):
            task_total = 0
        try:
            task_open = max(0, int(item.get("task_open") or 0))
        except (TypeError, ValueError):
            task_open = 0

        normalized.append(
            {
                "workflow_id": workflow_id,
                "organization_id": str(item.get("organization_id") or "").strip()
                or None,
                "project_id": str(item.get("project_id") or "").strip() or None,
                "project_name": str(item.get("project_name") or "—"),
                "current_state": str(item.get("current_state") or "unknown"),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "task_total": task_total,
                "task_open": task_open,
                "terminal": item.get("terminal") is True,
                "blocking_gate": blocking_gate,
                "rework": rework,
                "action_required": action,
                "action_label": _ACTION_LABELS[action],
            }
        )

    # Stable two-pass ordering: newest first within each operator-attention bucket.
    normalized.sort(
        key=lambda item: (item["updated_at"], item["workflow_id"]),
        reverse=True,
    )
    normalized.sort(key=lambda item: _ACTION_PRIORITY[item["action_required"]])
    return normalized


def overview_metrics(executions: list[dict[str, Any]]) -> dict[str, int]:
    active = [item for item in executions if not item["terminal"]]
    return {
        "active": len(active),
        "requires_action": sum(
            item["action_required"] in {"human_decision", "rejected"}
            for item in active
        ),
        "blocking": sum(item["blocking_gate"] is not None for item in active),
        "rework": sum(item["action_required"] == "rework_active" for item in active),
    }


def filter_executions_for_project(
    executions: list[dict[str, Any]], project_id: str | None
) -> list[dict[str, Any]]:
    """Filter only on an explicit backend-owned project_id relation."""
    if not project_id:
        return list(executions)
    return [item for item in executions if item["project_id"] == project_id]


def _manual_fallback() -> None:
    st.info("Angiv et Workflow ID manuelt nedenfor for at fortsætte i cockpittet.")


def _render_action_state(item: dict[str, Any]) -> None:
    action = item["action_required"]
    message = item["action_label"]
    if action == "human_decision":
        st.warning(f"⚠️ {message}")
    elif action == "rejected":
        st.error(f"🛑 {message}")
    elif action == "rework_active":
        st.info(f"🛠️ {message}")
    else:
        st.caption(message)


def render_operator_overview(client: DORAPIClient) -> None:
    """Render project-aware executions and open one in the canonical cockpit."""
    context = render_context_navigation(client)
    selected_project_id = context["selected_project_id"]

    active_workflow_id = str(
        st.session_state.get("workflow_input")
        or st.session_state.get("selected_workflow_id")
        or ""
    ).strip()
    if active_workflow_id:
        render_cockpit_lifecycle(client, active_workflow_id)
        st.divider()

    st.subheader("📡 Operator Overview")
    st.caption(
        "Backend-ejet overblik over executions, blocking gates og governed rework."
    )

    try:
        all_executions = normalize_execution_overview(client.get("/api/v1/execution"))
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        st.warning(f"Execution-overblik ikke tilgængeligt ({exc.status_code}): {exc}")
        _manual_fallback()
        return
    except Exception as exc:
        # The overview is read-only and must degrade without hiding the manual
        # cockpit path if its summary projection is temporarily unavailable.
        st.warning(f"Execution-overblik ikke tilgængeligt: {exc}")
        _manual_fallback()
        return

    executions = filter_executions_for_project(
        all_executions, selected_project_id
    )
    if selected_project_id:
        unlinked_count = sum(item["project_id"] is None for item in all_executions)
        st.caption(
            "Projektfilter bruger kun eksplicit backend `project_id`; "
            "workflow-navne bruges aldrig som provenance."
        )
        if unlinked_count:
            st.caption(
                f"{unlinked_count} legacy/unlinked execution(s) er kun synlige under "
                "Alle projekter eller via manuel Workflow ID fallback."
            )

    metrics = overview_metrics(executions)
    cols = st.columns(4)
    cols[0].metric("Aktive executions", metrics["active"])
    cols[1].metric("Kræver handling", metrics["requires_action"])
    cols[2].metric("Blocking", metrics["blocking"])
    cols[3].metric("Rework kører", metrics["rework"])

    active = [item for item in executions if not item["terminal"]]
    terminal_count = len(executions) - len(active)
    if not active:
        if selected_project_id:
            st.info("Ingen aktive, eksplicit linkede executions for det valgte projekt.")
        else:
            st.info("Ingen aktive executions rapporteret af backend.")
        if terminal_count:
            st.caption(
                f"{terminal_count} afsluttede execution(s) er skjult i v1-overblikket."
            )
        return

    for item in active:
        with st.container(border=True):
            st.markdown(f"### {item['project_name']}")
            project_context = (
                f" · project `{item['project_id']}`" if item["project_id"] else ""
            )
            st.caption(
                f"Workflow `{item['workflow_id']}`{project_context} · "
                f"fase `{item['current_state']}` · "
                f"åbne tasks {item['task_open']} / {item['task_total']} · "
                f"opdateret {item['updated_at'] or '—'}"
            )
            _render_action_state(item)

            blocker = item["blocking_gate"]
            if blocker:
                st.caption(
                    "Blocking gate: "
                    f"`{blocker.get('gate_id') or 'unknown'}` · "
                    f"decision `{blocker.get('decision') or 'pending'}`"
                )

            rework = item["rework"]
            if rework and rework.get("active"):
                st.caption(
                    "Aktiv rework: "
                    f"`{rework.get('task_id') or 'unknown'}` "
                    f"(`{rework.get('task_type') or 'unknown'}`)"
                )

            button_type = (
                "primary"
                if item["action_required"] in {"human_decision", "rejected"}
                else "secondary"
            )
            if st.button(
                "Åbn i Decision Cockpit",
                key=f"open_execution_{item['workflow_id']}",
                type=button_type,
            ):
                if item["project_id"]:
                    st.session_state["selected_project_id"] = item["project_id"]
                st.session_state["selected_workflow_id"] = item["workflow_id"]
                st.session_state.pop("workflow_input", None)
                st.rerun()

    if terminal_count:
        st.caption(
            f"{terminal_count} afsluttede execution(s) er skjult i v1-overblikket."
        )
