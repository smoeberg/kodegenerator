"""Fail-closed presentation helpers for the DOR Customer Portal.

The helpers in this module never create runtime state or authority. They only
project explicit backend-owned Project, Execution, Proposal and gate fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

UNKNOWN_STATUS = "Status kan ikke fastslås"
CANONICAL_JOURNEY = (
    "Sag",
    "Plan",
    "Aktivt arbejdsgrundlag",
    "Execution",
    "Proposal",
    "Beslutning",
)


class JourneyState(str, Enum):
    COMPLETED = "completed"
    CURRENT = "current"
    UPCOMING = "upcoming"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CustomerStatus:
    label: str
    state: JourneyState


@dataclass(frozen=True)
class CustomerProvenance:
    case_id: str
    plan_request_fingerprint: str
    workflow_id: str
    proposal_id: str | None = None


@dataclass(frozen=True)
class JourneyStep:
    label: str
    state: JourneyState


_PIPELINE_STATUS: dict[str, CustomerStatus] = {
    "requirements_draft": CustomerStatus("Planlægger", JourneyState.CURRENT),
    "requirements_validated": CustomerStatus("Planlægger", JourneyState.CURRENT),
    "requirements_approved": CustomerStatus("Plan godkendt", JourneyState.COMPLETED),
    "architecture_generating": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "architecture_generated": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "architecture_approved": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "contracts_generating": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "contracts_generated": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "contracts_approved": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "code_generating": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "code_generated": CustomerStatus("Arbejder", JourneyState.CURRENT),
    "tests_generating": CustomerStatus("Kontrollerer resultat", JourneyState.CURRENT),
    "tests_generated": CustomerStatus("Kontrollerer resultat", JourneyState.CURRENT),
    "tests_running": CustomerStatus("Kontrollerer resultat", JourneyState.CURRENT),
    "tests_passed": CustomerStatus("Kontrolleret", JourneyState.COMPLETED),
    "tests_failed": CustomerStatus("Arbejdet mislykkedes", JourneyState.FAILED),
    "deploying": CustomerStatus("Levering klargøres", JourneyState.CURRENT),
    "deployed": CustomerStatus("Levering klargjort", JourneyState.COMPLETED),
    "release_approved": CustomerStatus("Godkendt", JourneyState.COMPLETED),
    "released": CustomerStatus("Leveret", JourneyState.COMPLETED),
    "failed": CustomerStatus("Arbejdet mislykkedes", JourneyState.FAILED),
    "cancelled": CustomerStatus("Annulleret", JourneyState.FAILED),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def execution_state(execution: Mapping[str, Any] | None) -> str:
    if not isinstance(execution, Mapping):
        return ""
    return _text(
        execution.get("current_state")
        or execution.get("state_name")
        or execution.get("state")
    ).lower()


def project_status(project: Mapping[str, Any] | None) -> str:
    if not isinstance(project, Mapping):
        return ""
    return _text(project.get("status") or project.get("state")).lower()


def customer_execution_status(execution: Mapping[str, Any] | None) -> CustomerStatus:
    """Map only canonical pipeline states; all other inputs fail closed."""
    state = execution_state(execution)
    return _PIPELINE_STATUS.get(
        state,
        CustomerStatus(UNKNOWN_STATUS, JourneyState.UNKNOWN),
    )


def resolve_provenance(
    project: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    proposal: Mapping[str, Any] | None = None,
) -> CustomerProvenance | None:
    """Return only an exact backend-established Project/Plan/Execution chain."""
    case_id = _text(project.get("project_id"))
    plan_fingerprint = _text(project.get("active_plan_request_fingerprint"))
    if not case_id or len(plan_fingerprint) != 64:
        return None
    if not isinstance(execution, Mapping):
        return None
    if _text(execution.get("project_id")) != case_id:
        return None
    if _text(execution.get("plan_request_fingerprint")) != plan_fingerprint:
        return None
    workflow_id = _text(execution.get("workflow_id"))
    if not workflow_id:
        return None

    proposal_id: str | None = None
    if proposal is not None:
        if not isinstance(proposal, Mapping):
            return None
        if _text(proposal.get("workflow_id")) != workflow_id:
            return None
        proposal_id = _text(proposal.get("id")) or None
        if proposal_id is None:
            return None

    return CustomerProvenance(
        case_id=case_id,
        plan_request_fingerprint=plan_fingerprint,
        workflow_id=workflow_id,
        proposal_id=proposal_id,
    )


def decision_actions(gate: Mapping[str, Any]) -> tuple[str, ...]:
    """Project exact server-owned gate affordances into customer actions."""
    if not isinstance(gate, Mapping):
        return ()
    decision = _text(gate.get("decision")).lower()
    blocking = gate.get("blocking") is True
    resolved = gate.get("resolved") is True

    if blocking and not resolved and decision in {"", "pending", "none"}:
        return ("approve", "reject")
    if blocking and resolved and decision == "rejected" and gate.get("rework_allowed") is True:
        return ("request_changes",)
    return ()


def journey(
    project: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    gates: Sequence[Mapping[str, Any]] = (),
    proposals: Sequence[Mapping[str, Any]] = (),
) -> tuple[JourneyStep, ...]:
    """Build the six visible journey steps without inventing missing relationships."""
    case_id = _text(project.get("project_id"))
    case_state = JourneyState.COMPLETED if case_id else JourneyState.UNKNOWN
    plan = _text(project.get("active_plan_request_fingerprint"))
    plan_state = JourneyState.COMPLETED if len(plan) == 64 else JourneyState.UPCOMING

    pstatus = project_status(project)
    work_basis_state = (
        JourneyState.COMPLETED
        if plan and pstatus in {"active", "completion_pending", "completed", "archived"}
        else JourneyState.UPCOMING
    )

    if execution is None:
        execution_step = JourneyState.UPCOMING
    else:
        status = customer_execution_status(execution)
        execution_step = status.state
        if status.state is JourneyState.COMPLETED and execution_state(execution) not in {
            "released",
            "release_approved",
            "deployed",
        }:
            execution_step = JourneyState.CURRENT

    valid_proposals = [
        item
        for item in proposals
        if isinstance(item, Mapping)
        and resolve_provenance(project, execution, item) is not None
    ]
    proposal_state = (
        JourneyState.COMPLETED
        if valid_proposals
        else (JourneyState.UNKNOWN if proposals else JourneyState.UPCOMING)
    )

    actions = [decision_actions(gate) for gate in gates if isinstance(gate, Mapping)]
    if any("approve" in item or "reject" in item for item in actions):
        decision_state = JourneyState.CURRENT
    elif any("request_changes" in item for item in actions):
        decision_state = JourneyState.BLOCKED
    elif gates and all(gate.get("resolved") is True for gate in gates if isinstance(gate, Mapping)):
        decision_state = JourneyState.COMPLETED
    else:
        decision_state = JourneyState.UPCOMING

    return tuple(
        JourneyStep(label, state)
        for label, state in zip(
            CANONICAL_JOURNEY,
            (
                case_state,
                plan_state,
                work_basis_state,
                execution_step,
                proposal_state,
                decision_state,
            ),
            strict=True,
        )
    )


def completion_evidence(project: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Expose only backend-owned completion proof as verified evidence."""
    record_id = _text(project.get("completion_record_id"))
    status = project_status(project)
    archived_from = _text(project.get("archived_from_status")).lower()
    verified = bool(record_id) and (
        status == "completed" or (status == "archived" and archived_from == "completed")
    )
    if not verified:
        return ()
    return (
        {
            "label": "Levering verificeret",
            "record_id": record_id,
            "completed_by": _text(project.get("completed_by")),
            "completed_at": _text(project.get("completed_at")),
        },
    )


__all__ = [
    "CANONICAL_JOURNEY",
    "UNKNOWN_STATUS",
    "CustomerProvenance",
    "CustomerStatus",
    "JourneyState",
    "JourneyStep",
    "completion_evidence",
    "customer_execution_status",
    "decision_actions",
    "journey",
    "resolve_provenance",
]
