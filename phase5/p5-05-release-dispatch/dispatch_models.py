"""Immutable P5-05 release-dispatch models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Protocol


class DispatchError(ValueError):
    """Raised when a finalization cannot safely enter release dispatch."""


class DispatchState(str, Enum):
    DISPATCHED = "DISPATCHED"


class FinalizationLike(Protocol):
    """Structural contract for the P5-04 FinalizationRecord consumed by P5-05."""

    finalization_fingerprint: str
    outcome_fingerprint: str
    handoff_fingerprint: str
    request_id: str
    submission_id: str
    submission_fingerprint: str
    contract_fingerprint: str
    decision_fingerprint: str
    verifier_id: str
    outcome_value: str
    disposition: object
    state: object


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ReleaseDispatchRecord:
    """Immutable handoff record for downstream release infrastructure."""

    dispatch_id: str
    finalization_fingerprint: str
    outcome_fingerprint: str
    handoff_fingerprint: str
    request_id: str
    submission_id: str
    submission_fingerprint: str
    contract_fingerprint: str
    decision_fingerprint: str
    verifier_id: str
    outcome_value: str
    dispatched_at: datetime
    state: DispatchState = DispatchState.DISPATCHED
    dispatch_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        required = (
            self.dispatch_id,
            self.finalization_fingerprint,
            self.outcome_fingerprint,
            self.handoff_fingerprint,
            self.request_id,
            self.submission_id,
            self.submission_fingerprint,
            self.contract_fingerprint,
            self.decision_fingerprint,
        )
        if not all(required):
            raise DispatchError("dispatch identity is incomplete")
        if self.verifier_id != "p3-20":
            raise DispatchError("dispatch must preserve authoritative verifier p3-20")
        if self.outcome_value != "PASSED":
            raise DispatchError("only a passed finalization may be dispatched")
        if self.dispatched_at.tzinfo is None:
            object.__setattr__(
                self,
                "dispatched_at",
                self.dispatched_at.replace(tzinfo=timezone.utc),
            )
        object.__setattr__(
            self,
            "dispatch_fingerprint",
            _fingerprint(
                {
                    "dispatch_id": self.dispatch_id,
                    "finalization_fingerprint": self.finalization_fingerprint,
                    "outcome_fingerprint": self.outcome_fingerprint,
                    "handoff_fingerprint": self.handoff_fingerprint,
                    "request_id": self.request_id,
                    "submission_id": self.submission_id,
                    "submission_fingerprint": self.submission_fingerprint,
                    "contract_fingerprint": self.contract_fingerprint,
                    "decision_fingerprint": self.decision_fingerprint,
                    "verifier_id": self.verifier_id,
                    "outcome_value": self.outcome_value,
                    "dispatched_at": self.dispatched_at.isoformat(),
                    "state": self.state.value,
                }
            ),
        )
