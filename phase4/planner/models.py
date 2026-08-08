"""Immutable AI-6 planning contracts.

AI-6 may propose continuation work. It cannot authorize, execute, or mutate
AI-5 outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
import hashlib
import json

from phase4.outcome.models import OutcomeRecord, OutcomeStatus


class PlanStatus(str, Enum):
    PROPOSED = "proposed"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class ContinuationPolicy:
    """Pure planning policy; it does not grant execution authority."""

    max_retries: int = 0
    retryable_statuses: Tuple[OutcomeStatus, ...] = (OutcomeStatus.FAILED, OutcomeStatus.REJECTED)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


@dataclass(frozen=True)
class PlanRequest:
    """All state AI-6 needs to make a continuation proposal.

    request_fingerprint is supplied by the caller and is carried unchanged;
    AI-6 never invents or broadens the security identity of a request.
    """

    outcome: OutcomeRecord
    request_fingerprint: str
    action: str
    resource: str
    context_packet_id: str
    parameters: Tuple[Tuple[str, str], ...] = ()
    attempt: int = 0

    def __post_init__(self) -> None:
        if not self.request_fingerprint.strip():
            raise ValueError("request_fingerprint must be non-empty")
        for name in ("action", "resource", "context_packet_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.attempt < 0:
            raise ValueError("attempt must be non-negative")
        keys = [key for key, _ in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("parameter keys must be unique")


@dataclass(frozen=True)
class AgentActionProposal:
    """Immutable proposal. It is not an authorization decision or execution."""

    proposal_id: str
    outcome_id: str
    request_id: str
    request_fingerprint: str
    action: str
    resource: str
    context_packet_id: str
    parameters: Tuple[Tuple[str, str], ...]
    attempt: int
    reason: str
    status: PlanStatus = PlanStatus.PROPOSED

    @property
    def executable(self) -> bool:
        return False


def proposal_id_for(request: PlanRequest, reason: str) -> str:
    payload = {
        "outcome_id": request.outcome.outcome_id,
        "request_id": request.outcome.request_id,
        "request_fingerprint": request.request_fingerprint,
        "action": request.action,
        "resource": request.resource,
        "context_packet_id": request.context_packet_id,
        "parameters": sorted(list(request.parameters)),
        "attempt": request.attempt,
        "reason": reason,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
