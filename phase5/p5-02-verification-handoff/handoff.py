"""P5-02 verification handoff engine.

This layer binds and routes verification. It is deliberately incapable of
creating a verification decision itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Tuple
from uuid import uuid4

from .models import HandoffError, HandoffState, VerificationHandoff, VerificationRequest, VerificationResponse
from .p5_00_loader import load_p5_00

p5 = load_p5_00()


@dataclass(frozen=True)
class HandoffEvent:
    event_id: str
    request_id: str
    state: HandoffState
    actor_id: str
    occurred_at: datetime


class VerificationHandoffEngine:
    """Create deterministic requests and bind only authoritative P3-20 results."""

    def __init__(self, verifier_id: str = "p3-20", runtime_id: str = "p5-02-runtime") -> None:
        if verifier_id != "p3-20":
            raise HandoffError("P5-02 may only route to p3-20")
        if not runtime_id:
            raise HandoffError("runtime_id is required")
        self.verifier_id = verifier_id
        self.runtime_id = runtime_id
        self._requests: Dict[tuple[str, str, str], VerificationRequest] = {}
        self._events: Dict[str, Tuple[HandoffEvent, ...]] = {}

    def prepare(self, contract, submission, *, request_id: str | None = None, now: datetime | None = None) -> VerificationRequest:
        if submission.contract_fingerprint != contract.contract_fingerprint:
            raise HandoffError("submission contract fingerprint mismatch")
        if not submission.submission_id or not submission.submission_fingerprint:
            raise HandoffError("submission identity is incomplete")
        request_id = request_id or str(uuid4())
        key = (submission.submission_id, submission.submission_fingerprint, contract.contract_fingerprint)
        existing = self._requests.get(key)
        if existing is not None:
            return existing
        request = VerificationRequest(
            request_id=request_id,
            submission_id=submission.submission_id,
            submission_fingerprint=submission.submission_fingerprint,
            contract_fingerprint=contract.contract_fingerprint,
            verifier_id=self.verifier_id,
            contract=contract,
            submission=submission,
            created_at=now or datetime.now(timezone.utc),
        )
        self._requests[key] = request
        self._events[request.request_id] = (
            HandoffEvent(str(uuid4()), request.request_id, HandoffState.VERIFICATION_READY, self.runtime_id, request.created_at),
        )
        return request

    def dispatch(self, request: VerificationRequest, verifier: Callable[[VerificationRequest], object], *, now: datetime | None = None) -> VerificationHandoff:
        if request.verifier_id != self.verifier_id or request.verifier_id != "p3-20":
            raise HandoffError("verification route is not p3-20")
        self._ensure_known(request)
        timestamp = now or datetime.now(timezone.utc)
        self._append(request, HandoffState.VERIFICATION_DISPATCHED, timestamp)
        try:
            decision = verifier(request)
        except Exception as exc:
            self._append(request, HandoffState.VERIFICATION_REJECTED, datetime.now(timezone.utc))
            raise HandoffError("verification transport failed; no verification decision was created") from exc
        response = VerificationResponse(decision=decision, received_at=timestamp)
        handoff = self.bind_response(request, response)
        return handoff

    def bind_response(self, request: VerificationRequest, response: VerificationResponse) -> VerificationHandoff:
        self._ensure_known(request)
        decision = response.decision
        if decision.verifier != "p3-20":
            raise HandoffError("only p3-20 may issue verification decisions")
        if decision.submission_id != request.submission_id:
            raise HandoffError("decision submission mismatch")
        if decision.submission_fingerprint != request.submission_fingerprint:
            raise HandoffError("decision submission fingerprint mismatch")
        if decision.contract_fingerprint != request.contract_fingerprint:
            raise HandoffError("decision contract fingerprint mismatch")
        self._append(request, HandoffState.VERIFICATION_RETURNED, response.received_at)
        final_state = HandoffState.VERIFIED_PASSED if decision.passed else HandoffState.VERIFIED_FAILED
        self._append(request, final_state, response.received_at)
        return VerificationHandoff(request=request, state=final_state, response=response)

    def events(self, request: VerificationRequest) -> Tuple[HandoffEvent, ...]:
        self._ensure_known(request)
        return self._events[request.request_id]

    def _ensure_known(self, request: VerificationRequest) -> None:
        key = (request.submission_id, request.submission_fingerprint, request.contract_fingerprint)
        if self._requests.get(key) is not request:
            raise HandoffError("unknown or altered verification request")

    def _append(self, request: VerificationRequest, state: HandoffState, when: datetime) -> None:
        current = self._events[request.request_id]
        allowed = {
            HandoffState.VERIFICATION_READY: {HandoffState.VERIFICATION_DISPATCHED},
            HandoffState.VERIFICATION_DISPATCHED: {HandoffState.VERIFICATION_REJECTED, HandoffState.VERIFICATION_RETURNED},
            HandoffState.VERIFICATION_RETURNED: {HandoffState.VERIFIED_PASSED, HandoffState.VERIFIED_FAILED},
        }
        if state not in allowed.get(current[-1].state, set()):
            raise HandoffError(f"invalid handoff transition: {current[-1].state} -> {state}")
        self._events[request.request_id] = current + (HandoffEvent(str(uuid4()), request.request_id, state, self.runtime_id, when),)
