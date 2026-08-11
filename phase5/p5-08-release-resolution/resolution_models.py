from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from datetime import datetime, timezone


class ResolutionError(ValueError):
    """Raised when P5-08 cannot establish a safe resolution."""


class ResolutionDisposition(str, Enum):
    NO_ACTION = "NO_ACTION"
    RETRY_REQUESTED = "RETRY_REQUESTED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    RELEASE_BLOCKED = "RELEASE_BLOCKED"


_ALLOWED = frozenset(ResolutionDisposition)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResolutionPolicy:
    """Explicit deterministic policy consumed by the resolution boundary."""

    outcome_missing: ResolutionDisposition | None = None
    mismatch: ResolutionDisposition | None = None

    def __post_init__(self) -> None:
        for name, disposition in (
            ("outcome_missing", self.outcome_missing),
            ("mismatch", self.mismatch),
        ):
            if disposition is not None and disposition not in _ALLOWED:
                raise ResolutionError(f"invalid {name} disposition")
        if self.outcome_missing is ResolutionDisposition.NO_ACTION:
            raise ResolutionError("OUTCOME_MISSING cannot be resolved to NO_ACTION")
        if self.mismatch is ResolutionDisposition.RETRY_REQUESTED:
            raise ResolutionError("MISMATCH cannot request automatic retry")

    def canonical(self) -> dict[str, str | None]:
        return {
            "outcome_missing": self.outcome_missing.value if self.outcome_missing else None,
            "mismatch": self.mismatch.value if self.mismatch else None,
        }


@dataclass(frozen=True)
class ReleaseResolutionRecord:
    resolution_id: str
    reconciliation_id: str
    reconciliation_fingerprint: str
    dispatch_id: str
    outcome_id: str | None
    finalization_fingerprint: str
    verifier_id: str
    release_id: str
    disposition: ResolutionDisposition
    policy_fingerprint: str
    resolved_at: datetime
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        required = {
            "resolution_id": self.resolution_id,
            "reconciliation_id": self.reconciliation_id,
            "reconciliation_fingerprint": self.reconciliation_fingerprint,
            "dispatch_id": self.dispatch_id,
            "finalization_fingerprint": self.finalization_fingerprint,
            "verifier_id": self.verifier_id,
            "release_id": self.release_id,
            "policy_fingerprint": self.policy_fingerprint,
        }
        if any(not value for value in required.values()):
            raise ResolutionError("resolution identity is incomplete")
        if self.disposition not in _ALLOWED:
            raise ResolutionError("invalid resolution disposition")
        timestamp = self.resolved_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            object.__setattr__(self, "resolved_at", timestamp)
        payload = {
            "resolution_id": self.resolution_id,
            "reconciliation_id": self.reconciliation_id,
            "reconciliation_fingerprint": self.reconciliation_fingerprint,
            "dispatch_id": self.dispatch_id,
            "outcome_id": self.outcome_id,
            "finalization_fingerprint": self.finalization_fingerprint,
            "verifier_id": self.verifier_id,
            "release_id": self.release_id,
            "disposition": self.disposition.value,
            "policy_fingerprint": self.policy_fingerprint,
            "resolved_at": self.resolved_at.isoformat(),
        }
        object.__setattr__(self, "fingerprint", _fingerprint(payload))
