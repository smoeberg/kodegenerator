"""Immutable P5-03 outcome models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json


class OutcomeError(ValueError):
    """Raised when an authoritative verification outcome cannot be materialized."""


class OutcomeState(str, Enum):
    OUTCOME_MATERIALIZED = "OUTCOME_MATERIALIZED"


class OutcomeValue(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


def _canonical(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return {k: _canonical(v) for k, v in vars(value).items() if not k.startswith("_")}
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    return value


def fingerprint(value) -> str:
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    handoff_fingerprint: str
    request_id: str
    submission_id: str
    submission_fingerprint: str
    contract_fingerprint: str
    verifier_id: str
    value: OutcomeValue
    decision_fingerprint: str
    materialized_at: datetime
    state: OutcomeState = OutcomeState.OUTCOME_MATERIALIZED
    outcome_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not all((self.outcome_id, self.handoff_fingerprint, self.request_id, self.submission_id,
                    self.submission_fingerprint, self.contract_fingerprint, self.decision_fingerprint)):
            raise OutcomeError("outcome identity is incomplete")
        if self.verifier_id != "p3-20":
            raise OutcomeError("outcomes may only materialize p3-20 decisions")
        if self.materialized_at.tzinfo is None:
            object.__setattr__(self, "materialized_at", self.materialized_at.replace(tzinfo=timezone.utc))
        object.__setattr__(self, "outcome_fingerprint", fingerprint({
            "outcome_id": self.outcome_id,
            "handoff_fingerprint": self.handoff_fingerprint,
            "request_id": self.request_id,
            "submission_id": self.submission_id,
            "submission_fingerprint": self.submission_fingerprint,
            "contract_fingerprint": self.contract_fingerprint,
            "verifier_id": self.verifier_id,
            "value": self.value,
            "decision_fingerprint": self.decision_fingerprint,
            "materialized_at": self.materialized_at,
            "state": self.state,
        }))
