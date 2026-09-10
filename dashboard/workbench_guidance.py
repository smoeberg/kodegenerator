"""Pure presentation guidance for the case-first DOR workbench.

These helpers rank and label information that the backend already exposed. They do
not create actions, grant authority, or infer that a mutation is allowed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from dashboard.case_process_projection import AttentionState, CaseProcessProjection


@dataclass(frozen=True)
class CaseStatusBadge:
    label: str
    tone: str


@dataclass(frozen=True)
class GateGuidance:
    status_label: str
    explanation: str
    primary_action: str | None
    secondary_action: str | None


def case_status_badge(projection: CaseProcessProjection) -> CaseStatusBadge:
    """Return a human status label without changing process or authority semantics."""
    state = projection.attention_state
    if state is AttentionState.FAILED:
        return CaseStatusBadge("Fejl kræver opmærksomhed", "attention")
    if state is AttentionState.BLOCKED:
        return CaseStatusBadge("Blokeret", "attention")
    if state in {
        AttentionState.NEEDS_INPUT,
        AttentionState.NEEDS_DECISION,
        AttentionState.NEEDS_REVIEW,
    } or projection.attention_required:
        return CaseStatusBadge("Kræver dig", "attention")
    if state is AttentionState.CANCELLED:
        return CaseStatusBadge("Annulleret", "complete")
    if state is AttentionState.ARCHIVED:
        return CaseStatusBadge("Arkiveret", "complete")
    if state is AttentionState.COMPLETED:
        return CaseStatusBadge("Færdig", "complete")
    if projection.owner_type == "dor":
        return CaseStatusBadge("DOR arbejder", "working")
    if projection.owner_type == "external":
        return CaseStatusBadge("Afventer andre", "waiting")
    return CaseStatusBadge("Klar", "ready")


def primary_action_text(projection: CaseProcessProjection) -> str:
    """Describe the backend-projected next action; never invent an action."""
    if projection.next_action is not None:
        return projection.next_action.label
    return projection.attention_title


def gate_guidance(gate: Mapping[str, Any]) -> GateGuidance:
    """Prioritize only affordances present in a normalized backend gate record."""
    status = str(gate.get("status") or "")
    if status == "human_required":
        return GateGuidance(
            status_label="Afventer din beslutning",
            explanation="DOR kan ikke fortsætte denne del af sagen, før du har taget stilling.",
            primary_action="Godkend",
            secondary_action="Bed om ændringer",
        )

    if status == "rejected":
        can_rework = gate.get("can_rework") is True
        can_retry = gate.get("can_retry") is True
        if can_rework:
            return GateGuidance(
                status_label="Blokeret af din tidligere beslutning",
                explanation="DOR fortsætter ikke, før den afviste beslutning er håndteret gennem en backend-tilladt handling.",
                primary_action="Bed DOR om at rette",
                secondary_action="Åbn for ny vurdering" if can_retry else None,
            )
        if can_retry:
            return GateGuidance(
                status_label="Blokeret – ny vurdering er mulig",
                explanation="Backend tillader en ny beslutningsrunde, men ikke rework fra denne gate.",
                primary_action="Åbn for ny vurdering",
                secondary_action=None,
            )
        return GateGuidance(
            status_label="Blokeret",
            explanation="Backend har ikke åbnet en handling, der kan løse blokeringen endnu.",
            primary_action=None,
            secondary_action=None,
        )

    return GateGuidance(
        status_label="Ingen handling nødvendig",
        explanation="Denne gate kræver ikke en brugerhandling i det aktuelle backend-snapshot.",
        primary_action=None,
        secondary_action=None,
    )
