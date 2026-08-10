"""Immutable P5-07 release reconciliation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from datetime import datetime, timezone


class ReconciliationError(ValueError):
    """Raised when dispatch/outcome reconciliation is invalid."""


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    OUTCOME_MISSING = "OUTCOME_MISSING"
    MISMATCH = "MISMATCH"


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ReleaseReconciliationRecord:
    reconciliation_id: str
    dispatch_id: str
    outcome_id: str | None
    finalization_fingerprint: str
    status: ReconciliationStatus
    reason: str | None
    reconciled_at: datetime
    reconciliation_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.reconciliation_id or not self.dispatch_id or not self.finalization_fingerprint:
            raise ReconciliationError("reconciliation identity is incomplete")
        if self.status == ReconciliationStatus.OUTCOME_MISSING and self.outcome_id is not None:
            raise ReconciliationError("missing outcome cannot have an outcome_id")
        if self.status != ReconciliationStatus.OUTCOME_MISSING and not self.outcome_id:
            raise ReconciliationError("observed reconciliation requires outcome_id")
        if self.reconciled_at.tzinfo is None:
            object.__setattr__(self, "reconciled_at", self.reconciled_at.replace(tzinfo=timezone.utc))
        object.__setattr__(self, "reconciliation_fingerprint", _fingerprint({
            "reconciliation_id": self.reconciliation_id,
            "dispatch_id": self.dispatch_id,
            "outcome_id": self.outcome_id,
            "finalization_fingerprint": self.finalization_fingerprint,
            "status": self.status.value,
            "reason": self.reason,
            "reconciled_at": self.reconciled_at.isoformat(),
        }))
