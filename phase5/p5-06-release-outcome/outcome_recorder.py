"""P5-06 release outcome recording boundary."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from outcome_models import ReleaseOutcomeError, ReleaseOutcomeRecord, ReleaseOutcomeStatus


class ReleaseOutcomeRecorder:
    """Record externally observed release outcomes without creating authority."""

    def __init__(self, runtime_id: str = "p5-06-runtime") -> None:
        if not runtime_id:
            raise ReleaseOutcomeError("runtime_id is required")
        self.runtime_id = runtime_id
        self._records: dict[tuple[str, str], ReleaseOutcomeRecord] = {}

    def record(
        self,
        dispatch,
        *,
        status: ReleaseOutcomeStatus,
        external_reference: str,
        release_reference: str,
        outcome_id: str | None = None,
        observed_at: datetime | None = None,
        sink: Callable[[ReleaseOutcomeRecord], None] | None = None,
    ) -> ReleaseOutcomeRecord:
        self._validate_dispatch(dispatch)
        if not isinstance(status, ReleaseOutcomeStatus):
            raise ReleaseOutcomeError("unsupported release outcome status")
        if not external_reference or not release_reference:
            raise ReleaseOutcomeError("external_reference and release_reference are required")

        key = (dispatch.dispatch_id, external_reference)
        existing = self._records.get(key)
        if existing is not None:
            if existing.status != status or existing.release_reference != release_reference:
                raise ReleaseOutcomeError("conflicting outcome for dispatch and external reference")
            return existing

        record = ReleaseOutcomeRecord(
            outcome_id=outcome_id or str(uuid4()),
            dispatch_id=dispatch.dispatch_id,
            finalization_fingerprint=dispatch.finalization_fingerprint,
            outcome_fingerprint=dispatch.outcome_fingerprint,
            verifier_id=dispatch.verifier_id,
            status=status,
            external_reference=external_reference,
            release_reference=release_reference,
            observed_at=observed_at or datetime.now(timezone.utc),
        )
        if sink is not None:
            sink(record)
        self._records[key] = record
        return record

    def get(self, dispatch_id: str, external_reference: str) -> ReleaseOutcomeRecord | None:
        return self._records.get((dispatch_id, external_reference))

    @staticmethod
    def _validate_dispatch(dispatch) -> None:
        if dispatch is None:
            raise ReleaseOutcomeError("P5-06 requires a P5-05 dispatch record")
        if getattr(getattr(dispatch, "state", None), "value", getattr(dispatch, "state", None)) != "DISPATCHED":
            raise ReleaseOutcomeError("P5-06 requires DISPATCHED")
        if getattr(dispatch, "verifier_id", None) != "p3-20":
            raise ReleaseOutcomeError("P5-06 requires authoritative p3-20 dispatch provenance")
        for attr in ("dispatch_id", "finalization_fingerprint", "outcome_fingerprint"):
            if not getattr(dispatch, attr, None):
                raise ReleaseOutcomeError(f"dispatch {attr} is required")
