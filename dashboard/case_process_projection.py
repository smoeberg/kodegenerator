"""Canonical presentation projection for DOR cases and processes.

This module is deliberately presentation-only. It does not grant authority,
advance workflows, decide gates, or infer that an action will succeed. Backend
snapshots remain authoritative. The projection is shared by Sag, Mit arbejde
and Overblik so all three surfaces explain the same state consistently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ProcessPhase(str, Enum):
    CLARIFICATION = "afklaring"
    SOLUTION_DESIGN = "løsningsdesign"
    IMPLEMENTATION = "implementering"
    VERIFICATION = "verificering"
    DELIVERY = "levering"
    COMPLETED = "afsluttet"
    UNKNOWN = "ukendt"

    @property
    def label(self) -> str:
        return {
            self.CLARIFICATION: "Afklaring",
            self.SOLUTION_DESIGN: "Løsningsdesign",
            self.IMPLEMENTATION: "Implementering",
            self.VERIFICATION: "Verificering",
            self.DELIVERY: "Levering",
            self.COMPLETED: "Afsluttet",
            self.UNKNOWN: "Status ukendt",
        }[self]


CANONICAL_PROCESS_PHASES: tuple[ProcessPhase, ...] = (
    ProcessPhase.CLARIFICATION,
    ProcessPhase.SOLUTION_DESIGN,
    ProcessPhase.IMPLEMENTATION,
    ProcessPhase.VERIFICATION,
    ProcessPhase.DELIVERY,
    ProcessPhase.COMPLETED,
)


class AttentionState(str, Enum):
    NEEDS_INPUT = "needs_input"
    NEEDS_DECISION = "needs_decision"
    NEEDS_REVIEW = "needs_review"
    DOR_WORKING = "dor_working"
    REWORK_IN_PROGRESS = "rework_in_progress"
    WAITING_EXTERNAL = "waiting_external"
    BLOCKED = "blocked"
    FAILED = "failed"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"

    @property
    def owner(self) -> str:
        if self in {self.NEEDS_INPUT, self.NEEDS_DECISION, self.NEEDS_REVIEW, self.READY}:
            return "human"
        if self in {self.DOR_WORKING, self.REWORK_IN_PROGRESS}:
            return "dor"
        if self is self.WAITING_EXTERNAL:
            return "external"
        return "none"

    @property
    def requires_human_action(self) -> bool:
        return self in {
            self.NEEDS_INPUT,
            self.NEEDS_DECISION,
            self.NEEDS_REVIEW,
            self.READY,
            self.BLOCKED,
            self.FAILED,
        }


PIPELINE_STATE_TO_PHASE: dict[str, ProcessPhase] = {
    "requirements_draft": ProcessPhase.CLARIFICATION,
    "requirements_validated": ProcessPhase.CLARIFICATION,
    "requirements_approved": ProcessPhase.CLARIFICATION,
    "architecture_generating": ProcessPhase.SOLUTION_DESIGN,
    "architecture_generated": ProcessPhase.SOLUTION_DESIGN,
    "architecture_approved": ProcessPhase.SOLUTION_DESIGN,
    "contracts_generating": ProcessPhase.SOLUTION_DESIGN,
    "contracts_generated": ProcessPhase.SOLUTION_DESIGN,
    "contracts_approved": ProcessPhase.SOLUTION_DESIGN,
    "code_generating": ProcessPhase.IMPLEMENTATION,
    "code_generated": ProcessPhase.IMPLEMENTATION,
    "tests_generating": ProcessPhase.VERIFICATION,
    "tests_generated": ProcessPhase.VERIFICATION,
    "tests_running": ProcessPhase.VERIFICATION,
    "tests_passed": ProcessPhase.VERIFICATION,
    "tests_failed": ProcessPhase.VERIFICATION,
    "deploying": ProcessPhase.DELIVERY,
    "deployed": ProcessPhase.DELIVERY,
    "release_approved": ProcessPhase.DELIVERY,
    "released": ProcessPhase.COMPLETED,
    "failed": ProcessPhase.COMPLETED,
    "cancelled": ProcessPhase.COMPLETED,
}

PIPELINE_STATE_COPY: dict[str, str] = {
    "requirements_draft": "DOR arbejder med kravene",
    "requirements_validated": "Kravene er klar til gennemgang",
    "requirements_approved": "Kravene er godkendt",
    "architecture_generating": "DOR udarbejder løsningsforslaget",
    "architecture_generated": "Løsningsforslaget er klar",
    "architecture_approved": "Løsningsretningen er godkendt",
    "contracts_generating": "DOR udarbejder integrations- og datagrundlaget",
    "contracts_generated": "Grundlaget er klar til gennemgang",
    "contracts_approved": "Løsningsgrundlaget er godkendt",
    "code_generating": "DOR implementerer ændringen",
    "code_generated": "Implementeringen er klar til kontrol",
    "tests_generating": "DOR forbereder kontrollerne",
    "tests_generated": "Kontrollerne er klar",
    "tests_running": "DOR kontrollerer løsningen",
    "tests_passed": "De automatiske kontroller er bestået",
    "tests_failed": "Kontrollen fandt problemer",
    "deploying": "DOR klargør leveringen",
    "deployed": "Leveringen er klar til endelig godkendelse",
    "release_approved": "Leveringen er godkendt",
    "released": "Leveringen er færdig",
    "failed": "Stoppet på grund af fejl",
    "cancelled": "Arbejdet er stoppet",
}

PROJECT_STATE_COPY: dict[str, str] = {
    "created": "Klar til at starte",
    "launch_requested": "DOR klargør sagen",
    "active": "I gang",
    "completion_pending": "Klar til afslutning",
    "completed": "Færdig",
    "cancelled": "Stoppet",
    "archived": "Arkiveret",
}

GATE_COPY: dict[str, dict[str, str]] = {
    "gate_requirements_approval": {
        "approve": "Godkend kravene",
        "reject": "Bed om ændringer",
        "title": "Kravene er klar til din gennemgang",
    },
    "gate_architecture_approval": {
        "approve": "Godkend løsningsforslaget",
        "reject": "Bed om ændringer",
        "title": "Løsningsforslaget er klar",
    },
    "gate_contracts_approval": {
        "approve": "Godkend grundlaget",
        "reject": "Bed om ændringer",
        "title": "Integrations- og datagrundlaget er klar",
    },
    "gate_release_approval": {
        "approve": "Godkend leveringen",
        "reject": "Bed om ændringer",
        "title": "Leveringen er klar til din godkendelse",
    },
}

ACTION_COPY: dict[str, str] = {
    "launch": "Start sagen",
    "activate_scope": "Start arbejdet",
    "request_completion": "Klargør afslutning",
    "complete": "Afslut sagen",
    "cancel": "Stop sagen",
    "archive": "Arkivér sagen",
    "continue": "Fortsæt i ny sag",
    "approve": "Godkend",
    "reject": "Bed om ændringer",
    "retry": "Prøv igen",
    "rework": "Send til rework",
    "advance": "Fortsæt",
}

UNKNOWN_STATUS = "Status kan ikke fastslås"
UNKNOWN_EXPLANATION = (
    "Backend execution-snapshot mangler en genkendelig runtime-state. "
    "DOR viser derfor ingen næste handling."
)


@dataclass(frozen=True)
class NextBestAction:
    id: str
    label: str
    explanation: str
    confirmation_required: bool = False


@dataclass
class CaseProcessProjection:
    case_id: str
    title: str
    phase: ProcessPhase = ProcessPhase.CLARIFICATION
    human_status: str = "Klar til at starte"
    attention_state: AttentionState = AttentionState.READY
    attention_title: str = "Klar til at starte"
    attention_explanation: str = "Sagen er klar til næste skridt."
    owner_type: str = "human"
    next_action: NextBestAction | None = None
    allowed_actions: tuple[str, ...] = ()
    blockers: list[dict[str, str]] = field(default_factory=list)
    process_steps: list[dict[str, str]] = field(default_factory=list)
    evidence_completed: list[str] = field(default_factory=list)
    evidence_missing: list[str] = field(default_factory=list)
    technical_refs: dict[str, str | None] = field(default_factory=dict)
    raw_backend: dict[str, Any] = field(default_factory=dict)

    @property
    def attention_required(self) -> bool:
        return self.attention_state.requires_human_action


def _state(execution: Mapping[str, Any] | None) -> str:
    if execution is None:
        return ""
    return str(
        execution.get("current_state")
        or execution.get("state_name")
        or execution.get("state")
        or ""
    ).strip().lower()


def _project_status(project: Mapping[str, Any]) -> str:
    return str(project.get("status") or project.get("state") or "created").strip().lower()


def _blocking_gate(execution: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not execution:
        return None
    value = execution.get("blocking_gate")
    if isinstance(value, Mapping):
        return value
    gate_id = str(value or "").strip()
    return {"gate_id": gate_id} if gate_id else None


def _normalize_allowed_actions(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    result: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            raw = value.get("id") or value.get("action") or value.get("name")
        else:
            raw = value
        action = str(raw or "").strip().lower()
        if action and action not in result:
            result.append(action)
    return tuple(result)


def _collect_allowed_actions(
    project: Mapping[str, Any], execution: Mapping[str, Any] | None
) -> tuple[str, ...]:
    """Collect only actions explicitly exposed by backend snapshots.

    The resolver never derives authority from local state. This intentionally
    fails closed until the API exposes an allowed action.
    """
    values: list[str] = []
    for source in (project, execution or {}):
        for key in ("allowed_actions", "actions", "available_actions"):
            for action in _normalize_allowed_actions(source.get(key)):
                if action not in values:
                    values.append(action)
    return tuple(values)


def _gate_id(gate: Mapping[str, Any] | None) -> str | None:
    if not gate:
        return None
    return str(gate.get("gate_id") or gate.get("id") or "").strip() or None


def _candidate_action(allowed: tuple[str, ...], *candidates: str) -> str | None:
    allowed_set = set(allowed)
    for candidate in candidates:
        if candidate in allowed_set:
            return candidate
    return None


def _action_label(action: str, gate_id: str | None = None) -> str:
    gate = GATE_COPY.get(gate_id or "", {})
    if action in {"approve", "approved", "gate_approve"}:
        return gate.get("approve", "Godkend")
    if action in {"reject", "rejected", "gate_reject"}:
        return gate.get("reject", "Bed om ændringer")
    return ACTION_COPY.get(action, action.replace("_", " ").capitalize())


def _resolve_next_best_action(
    proj: CaseProcessProjection,
    project: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
) -> NextBestAction | None:
    """Choose one NBA strictly from backend-exposed allowed actions."""
    if proj.attention_state is AttentionState.UNKNOWN:
        return None

    allowed = proj.allowed_actions
    if not allowed:
        return None

    gate = _blocking_gate(execution)
    gate_id = _gate_id(gate)

    if proj.attention_state is AttentionState.NEEDS_DECISION:
        action = _candidate_action(allowed, "approve", "gate_approve", "approved")
        if action:
            title = GATE_COPY.get(gate_id or "", {}).get(
                "title", "Beslutningen er klar til din gennemgang"
            )
            return NextBestAction(
                id=action,
                label=_action_label(action, gate_id),
                explanation=title,
                confirmation_required=True,
            )

    if proj.attention_state is AttentionState.BLOCKED:
        action = _candidate_action(allowed, "rework", "retry")
        if action:
            return NextBestAction(
                id=action,
                label=_action_label(action, gate_id),
                explanation="Sagen er blokeret. Backend tillader denne næste handling.",
                confirmation_required=action == "rework",
            )
        return None

    if proj.attention_state in {
        AttentionState.DOR_WORKING,
        AttentionState.REWORK_IN_PROGRESS,
        AttentionState.COMPLETED,
        AttentionState.CANCELLED,
        AttentionState.ARCHIVED,
    }:
        return None

    project_status = _project_status(project)
    preferences = {
        "created": ("launch",),
        "launch_requested": ("activate_scope",),
        "active": ("advance", "request_completion", "cancel"),
        "completion_pending": ("complete", "cancel"),
        "completed": ("archive", "continue"),
        "cancelled": ("archive",),
        "archived": ("continue",),
    }
    action = _candidate_action(allowed, *preferences.get(project_status, ()))
    if not action:
        return None
    return NextBestAction(
        id=action,
        label=_action_label(action, gate_id),
        explanation="Backend har gjort denne handling tilgængelig for det aktuelle snapshot.",
        confirmation_required=action in {"complete", "cancel", "archive"},
    )


def _attention(
    project: Mapping[str, Any], execution: Mapping[str, Any] | None
) -> tuple[AttentionState, str, str]:
    project_status = _project_status(project)
    if project_status == "completed":
        return AttentionState.COMPLETED, "Sagen er færdig", "Der kræves ingen handling."
    if project_status == "cancelled":
        return AttentionState.CANCELLED, "Sagen er stoppet", "Der kræves ingen handling."
    if project_status == "archived":
        return AttentionState.ARCHIVED, "Sagen er arkiveret", "Der kræves ingen handling."
    if execution is None:
        return AttentionState.READY, "Klar til at starte", "Sagen er oprettet og klar."

    action_required = str(execution.get("action_required") or "none").strip().lower()
    rework = execution.get("rework")
    rework_active = (
        isinstance(rework, Mapping) and rework.get("active") is True
    ) or execution.get("rework_state") == "active"
    if rework_active or action_required == "rework_active":
        return (
            AttentionState.REWORK_IN_PROGRESS,
            "DOR arbejder på ændringerne",
            "Du skal ikke gøre noget lige nu.",
        )

    state = _state(execution)
    if state == "failed" or execution.get("error"):
        detail = str(execution.get("error") or execution.get("failure_reason") or "Se detaljerne.")
        return AttentionState.FAILED, "Kontrollen fandt et problem", detail

    gate = _blocking_gate(execution)
    gate_id = _gate_id(gate)
    if action_required == "human_decision":
        title = GATE_COPY.get(gate_id or "", {}).get(
            "title", "Din beslutning er nødvendig"
        )
        return AttentionState.NEEDS_DECISION, title, "Sagen afventer din beslutning."
    if action_required == "rejected":
        return AttentionState.BLOCKED, "Sagen er blokeret", "En afvist gate stopper processen."
    if action_required == "work_in_progress":
        return AttentionState.DOR_WORKING, "DOR arbejder på sagen", "Du skal ikke gøre noget lige nu."
    if action_required == "terminal":
        if state == "cancelled":
            return AttentionState.CANCELLED, "Arbejdet er stoppet", "Der kræves ingen handling."
        if state == "released":
            return AttentionState.COMPLETED, "Leveringen er færdig", "Der kræves ingen handling."
    return AttentionState.READY, "Klar til næste skridt", "Backend rapporterer ingen kendt blocker."


def _process_steps(phase: ProcessPhase) -> list[dict[str, str]]:
    if phase is ProcessPhase.UNKNOWN:
        return []
    current = CANONICAL_PROCESS_PHASES.index(phase)
    return [
        {
            "id": item.value,
            "label": item.label,
            "status": "completed" if index < current else "active" if index == current else "pending",
        }
        for index, item in enumerate(CANONICAL_PROCESS_PHASES)
    ]


def _evidence(
    phase: ProcessPhase, execution: Mapping[str, Any] | None
) -> tuple[list[str], list[str]]:
    if phase is ProcessPhase.UNKNOWN:
        return [], []

    state = _state(execution)
    milestones = [
        ("Krav", {"requirements_approved", "architecture_generating", "architecture_generated", "architecture_approved", "contracts_generating", "contracts_generated", "contracts_approved", "code_generating", "code_generated", "tests_generating", "tests_generated", "tests_running", "tests_passed", "tests_failed", "deploying", "deployed", "release_approved", "released"}),
        ("Løsningsgrundlag", {"contracts_approved", "code_generating", "code_generated", "tests_generating", "tests_generated", "tests_running", "tests_passed", "tests_failed", "deploying", "deployed", "release_approved", "released"}),
        ("Implementering", {"code_generated", "tests_generating", "tests_generated", "tests_running", "tests_passed", "tests_failed", "deploying", "deployed", "release_approved", "released"}),
        ("Kontrol", {"tests_passed", "deploying", "deployed", "release_approved", "released"}),
        ("Levering", {"deployed", "release_approved", "released"}),
    ]
    completed = [label for label, states in milestones if state in states]
    required_count = {
        ProcessPhase.CLARIFICATION: 1,
        ProcessPhase.SOLUTION_DESIGN: 2,
        ProcessPhase.IMPLEMENTATION: 3,
        ProcessPhase.VERIFICATION: 4,
        ProcessPhase.DELIVERY: 5,
        ProcessPhase.COMPLETED: 5,
    }[phase]
    expected = [label for label, _ in milestones[:required_count]]
    missing = [label for label in expected if label not in completed]
    return completed, missing


def project_case(
    case_id: str,
    project_data: Mapping[str, Any],
    execution_data: Mapping[str, Any] | None = None,
    delivery_data: Mapping[str, Any] | None = None,
) -> CaseProcessProjection:
    """Build the shared read-only projection for one DOR case."""
    state = _state(execution_data)
    unknown_execution_state = execution_data is not None and state not in PIPELINE_STATE_TO_PHASE

    if unknown_execution_state:
        phase = ProcessPhase.UNKNOWN
        human_status = UNKNOWN_STATUS
        attention_state = AttentionState.UNKNOWN
        attention_title = UNKNOWN_STATUS
        attention_explanation = UNKNOWN_EXPLANATION
        allowed_actions: tuple[str, ...] = ()
        completed: list[str] = []
        missing: list[str] = []
    else:
        phase = PIPELINE_STATE_TO_PHASE.get(state, ProcessPhase.CLARIFICATION)
        human_status = (
            PIPELINE_STATE_COPY.get(state)
            if state
            else PROJECT_STATE_COPY.get(_project_status(project_data), "Klar til at starte")
        ) or "Ukendt status"
        attention_state, attention_title, attention_explanation = _attention(
            project_data, execution_data
        )
        allowed_actions = _collect_allowed_actions(project_data, execution_data)
        completed, missing = _evidence(phase, execution_data)

    gate = _blocking_gate(execution_data)
    proj = CaseProcessProjection(
        case_id=str(case_id),
        title=str(project_data.get("name") or project_data.get("title") or f"Sag #{case_id}"),
        phase=phase,
        human_status=human_status,
        attention_state=attention_state,
        attention_title=attention_title,
        attention_explanation=attention_explanation,
        owner_type=attention_state.owner,
        allowed_actions=allowed_actions,
        blockers=(
            [{"type": "gate", "id": _gate_id(gate) or "unknown", "reason": str(gate.get("decision") or "pending")}]
            if gate and attention_state is AttentionState.BLOCKED
            else []
        ),
        process_steps=_process_steps(phase),
        evidence_completed=completed,
        evidence_missing=missing,
        technical_refs={
            "project_id": str(project_data.get("project_id") or "") or None,
            "workflow_id": str((execution_data or {}).get("workflow_id") or "") or None,
        },
        raw_backend={
            "project": dict(project_data),
            "execution": dict(execution_data) if execution_data is not None else None,
            "delivery": dict(delivery_data) if delivery_data else None,
        },
    )
    proj.next_action = _resolve_next_best_action(proj, project_data, execution_data)
    return proj
