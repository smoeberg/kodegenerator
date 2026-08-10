"""P5-04 terminal release-finalization boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from finalization_models import (
    FinalizationDisposition,
    FinalizationError,
    FinalizationRecord,
)


class ReleaseFinalizer:
    """Consume P5-03 authority and materialize a runtime release disposition."""

    def __init__(self, runtime_id: str = "p5-04-runtime") -> None:
        if not runtime_id:
            raise FinalizationError("runtime_id is required")
        self.runtime_id = runtime_id
        self._records: dict[str, FinalizationRecord] = {}

    def finalize(
        self,
        outcome,
        *,
        finalization_id: str | None = None,
        now: datetime | None = None,
    ) -> FinalizationRecord:
        self._validate_outcome(outcome)
        outcome_fp = outcome.outcome_fingerprint
        existing = self._records.get(outcome_fp)
        if existing is not None:
            return existing

        value = getattr(outcome.value, "value", outcome.value)
        disposition = (
            FinalizationDisposition.RELEASE_ELIGIBLE
            if value == "PASSED"
            else FinalizationDisposition.RELEASE_BLOCKED
        )
        record = FinalizationRecord(
            finalization_id=finalization_id or str(uuid4()),
            outcome_fingerprint=outcome_fp,
            handoff_fingerprint=outcome.handoff_fingerprint,
            request_id=outcome.request_id,
            submission_id=outcome.submission_id,
            submission_fingerprint=outcome.submission_fingerprint,
            contract_fingerprint=outcome.contract_fingerprint,
            decision_fingerprint=outcome.decision_fingerprint,
            verifier_id=outcome.verifier_id,
            outcome_value=value,
            disposition=disposition,
            finalized_at=now or datetime.now(timezone.utc),
        )
        self._records[outcome_fp] = record
        return record

    def get(self, outcome_fingerprint: str) -> FinalizationRecord | None:
        return self._records.get(outcome_fingerprint)

    @staticmethod
    def _validate_outcome(outcome) -> None:
        if outcome is None:
            raise FinalizationError("P5-04 requires a P5-03 outcome")
        if getattr(getattr(outcome, "state", None), "value", getattr(outcome, "state", None)) != "OUTCOME_MATERIALIZED":
            raise FinalizationError("P5-04 requires OUTCOME_MATERIALIZED")
        if getattr(outcome, "verifier_id", None) != "p3-20":
            raise FinalizationError("P5-04 requires an authoritative p3-20 outcome")
        for attr in (
            "outcome_fingerprint", "handoff_fingerprint", "request_id", "submission_id",
            "submission_fingerprint", "contract_fingerprint", "decision_fingerprint",
        ):
            if not getattr(outcome, attr, None):
                raise FinalizationError(f"outcome {attr} is required")
        value = getattr(getattr(outcome, "value", None), "value", getattr(outcome, "value", None))
        if value not in {"PASSED", "FAILED"}:
            raise FinalizationError("outcome value must be PASSED or FAILED")
