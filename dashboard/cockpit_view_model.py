"""Pure presentation helpers for the live execution cockpit.

The dashboard stays a thin client: these helpers only normalize API payloads
for presentation and construct payloads that match the canonical FastAPI
contracts. They do not own workflow transitions or authorization rules.
"""
from __future__ import annotations

from typing import Any, Mapping

_TERMINAL_STATES = {"released", "failed", "cancelled"}
_COMPLETED_TASK_STATES = {"succeeded", "success", "completed", "done"}


def build_execution_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable cockpit fields from an execution snapshot."""
    tasks_value = payload.get("tasks")
    tasks = [task for task in tasks_value if isinstance(task, Mapping)] if isinstance(tasks_value, list) else []
    completed = sum(
        1
        for task in tasks
        if str(task.get("status") or "").strip().lower() in _COMPLETED_TASK_STATES
    )
    current_state = str(payload.get("current_state") or payload.get("state_name") or "unknown")
    error = payload.get("error")

    if error:
        next_action = "Undersøg execution-fejlen før workflowet fortsættes."
    elif current_state.strip().lower() in _TERMINAL_STATES:
        next_action = "Workflowet er i en terminal tilstand."
    elif any(
        str(task.get("status") or "").strip().lower() not in _COMPLETED_TASK_STATES
        for task in tasks
    ):
        next_action = "Afvent eller undersøg aktive tasks før næste fase."
    else:
        next_action = "Vurder åbne quality gates og fortsæt workflowet når governance tillader det."

    return {
        "workflow_id": str(payload.get("workflow_id") or "—"),
        "project_name": str(payload.get("project_name") or "—"),
        "current_state": current_state,
        "task_total": len(tasks),
        "task_completed": completed,
        "task_open": max(len(tasks) - completed, 0),
        "error": str(error) if error else None,
        "next_action": next_action,
        "tasks": [dict(task) for task in tasks],
    }


def normalize_gates(payload: Any) -> list[dict[str, Any]]:
    """Normalize gate records while preserving backend governance semantics."""
    if not isinstance(payload, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        gate_id = str(item.get("id") or "").strip()
        if not gate_id:
            continue

        resolved = bool(item.get("resolved"))
        raw_decision = str(item.get("decision") or "").strip().lower()
        decision = raw_decision if raw_decision in {"approved", "rejected"} else None
        blocking = bool(item.get("blocking"))

        if decision == "rejected":
            status = "rejected"
        elif decision == "approved":
            status = "approved"
        elif resolved:
            status = "resolved"
        else:
            status = "human_required"

        normalized.append(
            {
                "id": gate_id,
                "name": str(item.get("name") or gate_id),
                "description": str(item.get("description") or "Ingen beskrivelse fra backend."),
                "resolved": resolved,
                "decision": decision,
                "blocking": blocking,
                "can_decide": not resolved,
                "status": status,
            }
        )
    return normalized


def gate_decision_payload(gate_id: str, decision: str) -> dict[str, str]:
    """Build the exact GateDecisionRequest payload accepted by FastAPI."""
    gate_id = gate_id.strip()
    decision = decision.strip().lower()
    if not gate_id:
        raise ValueError("gate_id is required")
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be 'approved' or 'rejected'")
    return {"gate_id": gate_id, "decision": decision}


def interpret_advance_error(status_code: int, message: str) -> dict[str, Any]:
    """Map a backend advance error to a cockpit-facing governance state."""
    text = str(message or "").strip()
    prefix = "workflow_blocked_by_gate:"
    if status_code == 409 and text.startswith(prefix):
        remainder = text[len(prefix):]
        gate_id, separator, decision = remainder.partition(":")
        gate_id = gate_id.strip() or "unknown"
        decision = decision.strip() if separator else "pending"
        decision = decision or "pending"
        return {
            "kind": "gate_blocked",
            "gate_id": gate_id,
            "decision": decision,
            "message": (
                f"Workflowet er blokeret af quality gate `{gate_id}` "
                f"(beslutning: `{decision}`)."
            ),
        }

    return {
        "kind": "api_error",
        "gate_id": None,
        "decision": None,
        "message": text or f"API-fejl ({status_code})",
    }


def normalize_proposals(payload: Any) -> list[dict[str, Any]]:
    """Normalize implementation proposals for human inspection."""
    if not isinstance(payload, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        files_value = item.get("files")
        files: list[dict[str, Any]] = []
        if isinstance(files_value, list):
            for index, file_item in enumerate(files_value, start=1):
                if not isinstance(file_item, Mapping):
                    continue
                raw = dict(file_item)
                display_name = str(
                    file_item.get("path")
                    or file_item.get("filename")
                    or file_item.get("name")
                    or f"Fil {index}"
                )
                diff = file_item.get("diff") or file_item.get("patch")
                files.append(
                    {
                        "display_name": display_name,
                        "diff": str(diff) if diff is not None else None,
                        "raw": raw,
                    }
                )
        normalized.append(
            {
                "id": str(item.get("id") or "—"),
                "title": str(item.get("title") or "Untitled proposal"),
                "summary": str(item.get("summary") or ""),
                "status": str(item.get("status") or "unknown"),
                "created_by": str(item.get("created_by") or "—"),
                "created_at": str(item.get("created_at") or "—"),
                "files": files,
                "raw": dict(item),
            }
        )
    return normalized
