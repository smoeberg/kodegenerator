"""Immutable P5-02 handoff models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fingerprinting import fingerprint


class HandoffError(ValueError):
    """Raised when a verification handoff cannot be safely bound."""


class HandoffState(str, Enum):
    VERIFICATION_READY = "VERIFICATION_READY"
    VERIFICATION_DISPATCHED = "VERIFICATION_DISPATCHED"
    VERIFICATION_REJECTED = "VERIFICATION_REJECTED"
    VERIFICATION_RETURNED = "VERIFICATION_RETURNED"
    VERIFIED_PASSED = "VERIFIED_PASSED"
    VERIFIED_FAILED = "VERIFIED_FAILED"


@dataclass(frozen=True)
class VerificationRequest:
    request_id: str
    submission_id: str
    submission_fingerprint: str
    contract_fingerprint: str
    verifier_id: str
    contract: object
    submission: object
    created_at: datetime
    request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not all((self.request_id, self.submission_id, self.submission_fingerprint, self.contract_fingerprint)):
            raise HandoffError("verification request identity is incomplete")
        if self.verifier_id != "p3-20":
            raise HandoffError("verification requests may only target p3-20")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=timezone.utc))
        object.__setattr__(self, "request_fingerprint", fingerprint({
            "request_id": self.request_id,
            "submission_id": self.submission_id,
            "submission_fingerprint": self.submission_fingerprint,
            "contract_fingerprint": self.contract_fingerprint,
            "verifier_id": self.verifier_id,
            "contract": self.contract,
            "submission": self.submission,
            "created_at": self.created_at,
        }))


@dataclass(frozen=True)
class VerificationResponse:
    decision: object
    received_at: datetime


@dataclass(frozen=True)
class VerificationHandoff:
    request: VerificationRequest
    state: HandoffState
    response: VerificationResponse | None = None
    handoff_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.response is not None:
            decision = self.response.decision
            if decision.verifier != "p3-20":
                raise HandoffError("only p3-20 decisions may be bound")
            if decision.submission_id != self.request.submission_id:
                raise HandoffError("decision submission mismatch")
            if decision.submission_fingerprint != self.request.submission_fingerprint:
                raise HandoffError("decision submission fingerprint mismatch")
            if decision.contract_fingerprint != self.request.contract_fingerprint:
                raise HandoffError("decision contract fingerprint mismatch")
            expected = HandoffState.VERIFIED_PASSED if decision.passed else HandoffState.VERIFIED_FAILED
            if self.state is not expected:
                raise HandoffError("handoff state does not match p3-20 decision")
        object.__setattr__(self, "handoff_fingerprint", fingerprint({
            "request": self.request.request_fingerprint,
            "state": self.state,
            "response": self.response,
        }))
