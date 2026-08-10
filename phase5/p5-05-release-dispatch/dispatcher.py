"""P5-05 release-dispatch boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from dispatch_models import DispatchError, FinalizationLike, ReleaseDispatchRecord


class ReleaseDispatcher:
    """Consume P5-04 finalization authority and create release dispatch records."""

    def __init__(self, runtime_id: str = "p5-05-runtime") -> None:
        if not runtime_id:
            raise DispatchError("runtime_id is required")
        self.runtime_id = runtime_id
        self._records: dict[str, ReleaseDispatchRecord] = {}

    def dispatch(
        self,
        finalization: FinalizationLike,
        *,
        dispatch_id: str | None = None,
        now: datetime | None = None,
        sink: Callable[[ReleaseDispatchRecord], None] | None = None,
    ) -> ReleaseDispatchRecord:
        self._validate_finalization(finalization)
        finalization_fp = finalization.finalization_fingerprint
        existing = self._records.get(finalization_fp)
        if existing is not None:
            return existing

        record = ReleaseDispatchRecord(
            dispatch_id=dispatch_id or str(uuid4()),
            finalization_fingerprint=finalization_fp,
            outcome_fingerprint=finalization.outcome_fingerprint,
            handoff_fingerprint=finalization.handoff_fingerprint,
            request_id=finalization.request_id,
            submission_id=finalization.submission_id,
            submission_fingerprint=finalization.submission_fingerprint,
            contract_fingerprint=finalization.contract_fingerprint,
            decision_fingerprint=finalization.decision_fingerprint,
            verifier_id=finalization.verifier_id,
            outcome_value=finalization.outcome_value,
            dispatched_at=now or datetime.now(timezone.utc),
        )

        if sink is not None:
            sink(record)

        self._records[finalization_fp] = record
        return record

    def get(self, finalization_fingerprint: str) -> ReleaseDispatchRecord | None:
        return self._records.get(finalization_fingerprint)

    @staticmethod
    def _validate_finalization(finalization: FinalizationLike) -> None:
        if finalization is None:
            raise DispatchError("P5-05 requires a P5-04 finalization record")

        state = getattr(getattr(finalization, "state", None), "value", getattr(finalization, "state", None))
        if state != "FINALIZED":
            raise DispatchError("P5-05 requires FINALIZED")

        disposition = getattr(
            getattr(finalization, "disposition", None),
            "value",
            getattr(finalization, "disposition", None),
        )
        if disposition != "RELEASE_ELIGIBLE":
            raise DispatchError("P5-05 requires RELEASE_ELIGIBLE finalization")

        if getattr(finalization, "verifier_id", None) != "p3-20":
            raise DispatchError("P5-05 requires authoritative p3-20 finalization")

        for attr in (
            "finalization_fingerprint",
            "outcome_fingerprint",
            "handoff_fingerprint",
            "request_id",
            "submission_id",
            "submission_fingerprint",
            "contract_fingerprint",
            "decision_fingerprint",
        ):
            if not getattr(finalization, attr, None):
                raise DispatchError(f"finalization {attr} is required")

        if getattr(finalization, "outcome_value", None) != "PASSED":
            raise DispatchError("only PASSED finalizations may be dispatched")
