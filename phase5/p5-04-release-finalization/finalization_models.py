"""Immutable P5-04 finalization models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json


class FinalizationError(ValueError):
    """Raised when an outcome cannot be safely finalized."""


class FinalizationState(str, Enum):
    FINALIZED = "FINALIZED"


class FinalizationDisposition(str, Enum):
    RELEASE_ELIGIBLE = "RELEASE_ELIGIBLE"
    RELEASE_BLOCKED = "RELEASE_BLOCKED"


def _fingerprint(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class FinalizationRecord:
    finalization_id: str
    outcome_fingerprint: str
    handoff_fingerprint: str
    request_id: str
    submission_id: str
    submission_fingerprint: str
    contract_fingerprint: str
    decision_fingerprint: str
    verifier_id: str
    outcome_value: str
    disposition: FinalizationDisposition
    finalized_at: datetime
    state: FinalizationState = FinalizationState.FINALIZED
    finalization_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        required = (
            self.finalization_id, self.outcome_fingerprint, self.handoff_fingerprint,
            self.request_id, self.submission_id, self.submission_fingerprint,
            self.contract_fingerprint, self.decision_fingerprint,
        )
        if not all(required):
            raise FinalizationError("finalization identity is incomplete")
        if self.verifier_id != "p3-20":
            raise FinalizationError("only p3-20 outcomes may be finalized")
        if self.outcome_value not in {"PASSED", "FAILED"}:
            raise FinalizationError("outcome value must be PASSED or FAILED")
        expected = (FinalizationDisposition.RELEASE_ELIGIBLE
                    if self.outcome_value == "PASSED"
                    else FinalizationDisposition.RELEASE_BLOCKED)
        if self.disposition is not expected:
            raise FinalizationError("disposition does not match authoritative outcome")
        if self.finalized_at.tzinfo is None:
            object.__setattr__(self, "finalized_at", self.finalized_at.replace(tzinfo=timezone.utc))
        object.__setattr__(self, "finalization_fingerprint", _fingerprint({
            "finalization_id": self.finalization_id,
            "outcome_fingerprint": self.outcome_fingerprint,
            "handoff_fingerprint": self.handoff_fingerprint,
            "request_id": self.request_id,
            "submission_id": self.submission_id,
            "submission_fingerprint": self.submission_fingerprint,
            "contract_fingerprint": self.contract_fingerprint,
            "decision_fingerprint": self.decision_fingerprint,
            "verifier_id": self.verifier_id,
            "outcome_value": self.outcome_value,
            "disposition": self.disposition.value,
            "finalized_at": self.finalized_at.isoformat(),
            "state": self.state.value,
        }))
