"""Human-facing evidence projection for one DOR case.

This module deliberately separates process-derived signals from authoritative
completion evidence. Pipeline state may explain progress, but it is never
presented as an immutable proof. A verified delivery item is only emitted when
the backend project snapshot contains a completion record produced by the
server-owned completion evidence verifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class EvidenceStatus(str, Enum):
    COMPLETED = "completed"
    PENDING = "pending"
    FAILED = "failed"
    VERIFIED = "verified"


@dataclass(frozen=True)
class CaseEvidenceItem:
    id: str
    label: str
    status: EvidenceStatus
    detail: str
    authoritative: bool = False


@dataclass(frozen=True)
class CaseEvidenceProjection:
    process_items: tuple[CaseEvidenceItem, ...]
    verified_items: tuple[CaseEvidenceItem, ...]


_REQUIREMENTS_DONE = {
    "requirements_approved",
    "architecture_generating",
    "architecture_generated",
    "architecture_approved",
    "contracts_generating",
    "contracts_generated",
    "contracts_approved",
    "code_generating",
    "code_generated",
    "tests_generating",
    "tests_generated",
    "tests_running",
    "tests_passed",
    "tests_failed",
    "deploying",
    "deployed",
    "release_approved",
    "released",
}

_SOLUTION_DONE = {
    "contracts_approved",
    "code_generating",
    "code_generated",
    "tests_generating",
    "tests_generated",
    "tests_running",
    "tests_passed",
    "tests_failed",
    "deploying",
    "deployed",
    "release_approved",
    "released",
}

_IMPLEMENTATION_DONE = {
    "code_generated",
    "tests_generating",
    "tests_generated",
    "tests_running",
    "tests_passed",
    "tests_failed",
    "deploying",
    "deployed",
    "release_approved",
    "released",
}

_VERIFICATION_DONE = {
    "tests_passed",
    "deploying",
    "deployed",
    "release_approved",
    "released",
}

_DELIVERY_READY = {"deployed", "release_approved", "released"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _state(execution: Mapping[str, Any] | None) -> str:
    if not execution:
        return ""
    return _text(
        execution.get("current_state")
        or execution.get("state_name")
        or execution.get("state")
    ).lower()


def _process_item(
    *,
    item_id: str,
    label: str,
    done: bool,
    completed_detail: str,
    pending_detail: str,
) -> CaseEvidenceItem:
    return CaseEvidenceItem(
        id=item_id,
        label=label,
        status=EvidenceStatus.COMPLETED if done else EvidenceStatus.PENDING,
        detail=completed_detail if done else pending_detail,
        authoritative=False,
    )


def _completion_is_verified(project: Mapping[str, Any]) -> bool:
    record_id = _text(project.get("completion_record_id"))
    status = _text(project.get("status") or project.get("state")).lower()
    if not record_id:
        return False
    if status == "completed":
        return True
    return status == "archived" and _text(project.get("archived_from_status")).lower() == "completed"


def build_case_evidence(
    project: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
) -> CaseEvidenceProjection:
    """Project human-readable evidence without upgrading inference into proof."""
    state = _state(execution)

    process_items = [
        _process_item(
            item_id="requirements",
            label="Krav godkendt",
            done=state in _REQUIREMENTS_DONE,
            completed_detail="Pipeline-status viser, at kravfasen er passeret.",
            pending_detail="Kravfasen er endnu ikke passeret i det aktuelle pipeline-snapshot.",
        ),
        _process_item(
            item_id="solution",
            label="Løsningsgrundlag godkendt",
            done=state in _SOLUTION_DONE,
            completed_detail="Pipeline-status viser, at løsningsgrundlaget er passeret.",
            pending_detail="Løsningsgrundlaget er endnu ikke passeret i det aktuelle pipeline-snapshot.",
        ),
        _process_item(
            item_id="implementation",
            label="Implementering gennemført",
            done=state in _IMPLEMENTATION_DONE,
            completed_detail="Pipeline-status viser, at implementeringen er produceret.",
            pending_detail="Implementeringen er endnu ikke produceret i det aktuelle pipeline-snapshot.",
        ),
    ]

    if state == "tests_failed":
        process_items.append(
            CaseEvidenceItem(
                id="verification",
                label="Automatiske kontroller",
                status=EvidenceStatus.FAILED,
                detail="Pipeline-status viser, at de automatiske kontroller fandt fejl.",
                authoritative=False,
            )
        )
    else:
        process_items.append(
            _process_item(
                item_id="verification",
                label="Automatiske kontroller bestået",
                done=state in _VERIFICATION_DONE,
                completed_detail="Pipeline-status viser, at de automatiske kontroller er bestået.",
                pending_detail="Der er endnu ikke et bestået testtrin i det aktuelle pipeline-snapshot.",
            )
        )

    process_items.append(
        _process_item(
            item_id="delivery",
            label="Levering klargjort",
            done=state in _DELIVERY_READY,
            completed_detail="Pipeline-status viser, at leveringen er klargjort eller længere fremme.",
            pending_detail="Leveringen er endnu ikke klargjort i det aktuelle pipeline-snapshot.",
        )
    )

    verified_items: list[CaseEvidenceItem] = []
    if _completion_is_verified(project):
        completed_by = _text(project.get("completed_by"))
        completed_at = _text(project.get("completed_at"))
        provenance = "Backend har registreret et immutable afslutningsbevis."
        if completed_by and completed_at:
            provenance += f" Afsluttet af {completed_by} · {completed_at}."
        elif completed_by:
            provenance += f" Afsluttet af {completed_by}."
        elif completed_at:
            provenance += f" Registreret {completed_at}."
        verified_items.append(
            CaseEvidenceItem(
                id="completion_record",
                label="Levering verificeret",
                status=EvidenceStatus.VERIFIED,
                detail=provenance,
                authoritative=True,
            )
        )

    return CaseEvidenceProjection(
        process_items=tuple(process_items),
        verified_items=tuple(verified_items),
    )


__all__ = [
    "CaseEvidenceItem",
    "CaseEvidenceProjection",
    "EvidenceStatus",
    "build_case_evidence",
]
