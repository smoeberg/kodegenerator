"""Lifecycle-oriented presentation for the canonical Decision Cockpit.

This module is presentation-only. It reads the existing Execution API snapshots,
prioritizes operator attention, and renders a compact lifecycle summary. Backend
state remains authoritative for workflow transitions and gate decisions.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_view_model import (
    build_execution_summary,
    normalize_gates,
    normalize_proposals,
)

_TERMINAL_STATES = {"released", "failed", "cancelled"}


def build_cockpit_lifecycle(
    execution_payload: Mapping[str, Any],
    gates_payload: Any,
    proposals_payload: Any,
    *,
    gates_available: bool = True,
    proposals_available: bool = True,
) -> dict[str, Any]:
    """Build a presentation-only lifecycle snapshot from canonical API payloads."""
    summary = build_execution_summary(execution_payload)
    gates = normalize_gates(gates_payload) if gates_available else []
    proposals = normalize_proposals(proposals_payload) if proposals_available else []

    human_required = [
        gate for gate in gates if gate["status"] == "human_required" and gate["can_decide"]
    ]
    rejected_blocking = [
        gate
        for gate in gates
        if gate["status"] == "rejected" and gate["blocking"]
    ]
    active_rework = [gate for gate in gates if gate["rework_active"]]
    blocking = [gate for gate in gates if gate["blocking"]]
    terminal = summary["current_state"].strip().lower() in _TERMINAL_STATES

    if summary["error"]:
        attention = {
            "kind": "error",
            "title": "Execution kræver fejlsøgning",
            "detail": summary["error"],
            "focus": "Undersøg execution-fejlen før næste operatorhandling.",
        }
    elif not gates_available:
        attention = {
            "kind": "warning",
            "title": "Gate-status er utilgængelig",
            "detail": "Cockpittet kan ikke verificere den aktuelle governance-state.",
            "focus": "Undlad at antage, at workflowet er klar til progression.",
        }
    elif human_required:
        gate_ids = ", ".join(gate["id"] for gate in human_required)
        attention = {
            "kind": "warning",
            "title": "Human decision kræves",
            "detail": f"Åben gate: {gate_ids}.",
            "focus": "Afgør den åbne quality gate nedenfor.",
        }
    elif active_rework:
        task_ids = ", ".join(
            gate["rework_task_id"] or gate["id"] for gate in active_rework
        )
        attention = {
            "kind": "info",
            "title": "Governed rework kører",
            "detail": f"Aktiv rework: {task_ids}.",
            "focus": "Afvent backend-resultatet; gaten forbliver fail-closed imens.",
        }
    elif rejected_blocking:
        gate_ids = ", ".join(gate["id"] for gate in rejected_blocking)
        attention = {
            "kind": "error",
            "title": "Workflowet er blokeret",
            "detail": f"Rejected/blocking gate: {gate_ids}.",
            "focus": "Vælg kun retry eller rework, når backend eksplicit tilbyder handlingen.",
        }
    elif summary["task_open"]:
        attention = {
            "kind": "info",
            "title": "Arbejde er stadig aktivt",
            "detail": f"{summary['task_open']} task(s) er ikke færdige endnu.",
            "focus": "Følg task-status og realtime events før næste vurdering.",
        }
    elif terminal:
        attention = {
            "kind": "success",
            "title": "Execution er afsluttet",
            "detail": f"Workflowet er i terminal state `{summary['current_state']}`.",
            "focus": "Brug Evidence Trace til afsluttende dokumentation og audit.",
        }
    else:
        attention = {
            "kind": "success",
            "title": "Ingen kendt lokal blocker i snapshot",
            "detail": "Tasks og synlige gates kræver ikke handling i det aktuelle snapshot.",
            "focus": "Backend afgør fortsat, om Advance accepteres.",
        }

    gate_value = "utilgængelig"
    if gates_available:
        gate_value = (
            f"{len(human_required)} human · {len(blocking)} blocking"
            if gates
            else "0 gates"
        )
    proposal_value = "utilgængelig" if not proposals_available else str(len(proposals))

    return {
        "workflow_id": summary["workflow_id"],
        "project_name": summary["project_name"],
        "current_state": summary["current_state"],
        "task_value": f"{summary['task_completed']} / {summary['task_total']}",
        "gate_value": gate_value,
        "proposal_value": proposal_value,
        "evidence_value": (
            "klar" if gates_available and proposals_available else "delvist"
        ),
        "attention": attention,
    }


def _render_attention(attention: Mapping[str, str]) -> None:
    message = f"**{attention['title']}** — {attention['detail']}"
    kind = attention["kind"]
    if kind == "error":
        st.error(message)
    elif kind == "warning":
        st.warning(message)
    elif kind == "success":
        st.success(message)
    else:
        st.info(message)
    st.markdown(f"**Operatorfokus:** {attention['focus']}")


def render_cockpit_lifecycle(client: DORAPIClient, workflow_id: str) -> None:
    """Render compact lifecycle and operator-attention state for one workflow."""
    workflow_id = str(workflow_id or "").strip()
    if not workflow_id:
        return

    try:
        execution_payload = client.get(f"/api/v1/execution/{workflow_id}")
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        st.caption(f"Cockpit lifecycle ikke tilgængelig ({exc.status_code}): {exc}")
        return

    gates_available = True
    try:
        gates_payload = client.get(f"/api/v1/execution/{workflow_id}/gates")
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        gates_payload = []
        gates_available = False

    proposals_available = True
    try:
        proposals_payload = client.get(f"/api/v1/execution/{workflow_id}/proposals")
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        proposals_payload = []
        proposals_available = False

    lifecycle = build_cockpit_lifecycle(
        execution_payload,
        gates_payload,
        proposals_payload,
        gates_available=gates_available,
        proposals_available=proposals_available,
    )

    st.subheader("🧭 Decision Cockpit lifecycle")
    st.caption(
        f"Workflow `{lifecycle['workflow_id']}` · projekt `{lifecycle['project_name']}` · "
        f"state `{lifecycle['current_state']}`"
    )

    columns = st.columns(5)
    columns[0].metric("Execution", lifecycle["current_state"])
    columns[1].metric("Tasks færdige", lifecycle["task_value"])
    columns[2].metric("Quality gates", lifecycle["gate_value"])
    columns[3].metric("Proposals", lifecycle["proposal_value"])
    columns[4].metric("Evidence", lifecycle["evidence_value"])

    _render_attention(lifecycle["attention"])
    st.caption(
        "Lifecycle-visningen er presentation-only. Execution API er fortsat eneste "
        "authority for transitions, gate-state, retry og rework."
    )
