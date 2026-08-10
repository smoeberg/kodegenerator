"""P5-03 authoritative outcome materializer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from models import OutcomeError, OutcomeRecord, OutcomeValue


class OutcomeMaterializer:
    """Materialize, but never create, an authoritative P3-20 outcome."""

    def __init__(self, runtime_id: str = "p5-03-runtime") -> None:
        if not runtime_id:
            raise OutcomeError("runtime_id is required")
        self.runtime_id = runtime_id
        self._outcomes: Dict[str, OutcomeRecord] = {}

    def materialize(self, handoff, *, outcome_id: str | None = None, now: datetime | None = None) -> OutcomeRecord:
        request = getattr(handoff, "request", None)
        response = getattr(handoff, "response", None)
        state = getattr(handoff, "state", None)
        if request is None or response is None:
            raise OutcomeError("P5-03 requires a completed P5-02 handoff")
        if getattr(state, "value", state) not in {"VERIFIED_PASSED", "VERIFIED_FAILED"}:
            raise OutcomeError("outcome materialization requires a final P5-02 verification state")

        decision = response.decision
        if getattr(decision, "verifier", None) != "p3-20":
            raise OutcomeError("only p3-20 decisions may be materialized")
        for attr in ("submission_id", "submission_fingerprint", "contract_fingerprint"):
            if not getattr(decision, attr, None):
                raise OutcomeError(f"decision {attr} is required")
        if decision.submission_id != request.submission_id:
            raise OutcomeError("decision submission mismatch")
        if decision.submission_fingerprint != request.submission_fingerprint:
            raise OutcomeError("decision submission fingerprint mismatch")
        if decision.contract_fingerprint != request.contract_fingerprint:
            raise OutcomeError("decision contract fingerprint mismatch")

        handoff_fp = getattr(handoff, "handoff_fingerprint", None)
        if not handoff_fp:
            raise OutcomeError("handoff fingerprint is required")
        existing = self._outcomes.get(handoff_fp)
        if existing is not None:
            return existing

        decision_fp = getattr(decision, "decision_fingerprint", None)
        if not decision_fp:
            decision_fp = _decision_fingerprint(decision)
        value = OutcomeValue.PASSED if bool(decision.passed) else OutcomeValue.FAILED
        record = OutcomeRecord(
            outcome_id=outcome_id or str(uuid4()),
            handoff_fingerprint=handoff_fp,
            request_id=request.request_id,
            submission_id=request.submission_id,
            submission_fingerprint=request.submission_fingerprint,
            contract_fingerprint=request.contract_fingerprint,
            verifier_id="p3-20",
            value=value,
            decision_fingerprint=decision_fp,
            materialized_at=now or datetime.now(timezone.utc),
        )
        self._outcomes[handoff_fp] = record
        return record

    def get(self, handoff_fingerprint: str) -> OutcomeRecord | None:
        return self._outcomes.get(handoff_fingerprint)


def _decision_fingerprint(decision) -> str:
    """Fallback content fingerprint; it is never treated as a new authority."""
    import hashlib
    import json

    payload = {
        "verifier": decision.verifier,
        "submission_id": decision.submission_id,
        "submission_fingerprint": decision.submission_fingerprint,
        "contract_fingerprint": decision.contract_fingerprint,
        "passed": bool(decision.passed),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
