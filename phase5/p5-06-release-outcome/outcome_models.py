"""Immutable P5-06 release outcome models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json


class ReleaseOutcomeError(ValueError):
    """Raised when an observed release outcome violates the P5-06 contract."""


class ReleaseOutcomeStatus(str, Enum):
    RELEASE_ACCEPTED = "RELEASE_ACCEPTED"
    RELEASE_REJECTED = "RELEASE_REJECTED"
    RELEASE_FAILED = "RELEASE_FAILED"


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ReleaseOutcomeRecord:
    """Immutable append-only observation of an external release outcome."""

    outcome_id: str
    dispatch_id: str
    finalization_fingerprint: str
    outcome_fingerprint: str
    verifier_id: str
    status: ReleaseOutcomeStatus
    external_reference: str
    release_reference: str
    observed_at: datetime
    outcome_record_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        required = (
            self.outcome_id,
            self.dispatch_id,
            self.finalization_fingerprint,
            self.outcome_fingerprint,
            self.external_reference,
            self.release_reference,
        )
        if not all(required):
            raise ReleaseOutcomeError("release outcome identity is incomplete")
        if self.verifier_id != "p3-20":
            raise ReleaseOutcomeError("release outcome must preserve authoritative verifier p3-20")
        if not isinstance(self.status, ReleaseOutcomeStatus):
            raise ReleaseOutcomeError("unsupported release outcome status")
        if self.observed_at.tzinfo is None:
            object.__setattr__(self, "observed_at", self.observed_at.replace(tzinfo=timezone.utc))
        object.__setattr__(
            self,
            "outcome_record_fingerprint",
            _fingerprint(
                {
                    "outcome_id": self.outcome_id,
                    "dispatch_id": self.dispatch_id,
                    "finalization_fingerprint": self.finalization_fingerprint,
                    "outcome_fingerprint": self.outcome_fingerprint,
                    "verifier_id": self.verifier_id,
                    "status": self.status.value,
                    "external_reference": self.external_reference,
                    "release_reference": self.release_reference,
                    "observed_at": self.observed_at.isoformat(),
                }
            ),
        )

    def canonical_dict(self) -> dict[str, str]:
        return {
            "dispatch_id": self.dispatch_id,
            "external_reference": self.external_reference,
            "finalization_fingerprint": self.finalization_fingerprint,
            "observed_at": self.observed_at.isoformat(),
            "outcome_fingerprint": self.outcome_fingerprint,
            "outcome_id": self.outcome_id,
            "release_reference": self.release_reference,
            "status": self.status.value,
            "verifier_id": self.verifier_id,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
