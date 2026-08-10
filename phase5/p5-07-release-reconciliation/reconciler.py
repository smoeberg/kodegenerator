"""P5-07 observational release reconciliation boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from reconciliation_models import (
    ReconciliationError,
    ReconciliationStatus,
    ReleaseReconciliationRecord,
)


class ReleaseReconciler:
    """Compare a P5-05 dispatch with a P5-06 observed outcome."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str | None], ReleaseReconciliationRecord] = {}

    def reconcile(self, dispatch, outcome=None, *, reconciliation_id=None, now=None):
        if dispatch is None:
            raise ReconciliationError("P5-07 requires a release dispatch")
        for attr in ("dispatch_id", "finalization_fingerprint", "verifier_id"):
            if not getattr(dispatch, attr, None):
                raise ReconciliationError(f"dispatch {attr} is required")
        if dispatch.verifier_id != "p3-20":
            raise ReconciliationError("dispatch must preserve authoritative verifier p3-20")

        outcome_id = getattr(outcome, "outcome_id", None) if outcome is not None else None
        key = (dispatch.dispatch_id, outcome_id)
        existing = self._records.get(key)
        if existing is not None:
            return existing

        if outcome is None:
            status = ReconciliationStatus.OUTCOME_MISSING
            reason = "no observed release outcome"
        else:
            required = (
                "outcome_id",
                "dispatch_id",
                "finalization_fingerprint",
                "verifier_id",
            )
            for attr in required:
                if not getattr(outcome, attr, None):
                    raise ReconciliationError(f"outcome {attr} is required")

            mismatches = []
            for attr in ("dispatch_id", "finalization_fingerprint", "verifier_id"):
                if getattr(outcome, attr) != getattr(dispatch, attr):
                    mismatches.append(attr)
            status = ReconciliationStatus.RECONCILED if not mismatches else ReconciliationStatus.MISMATCH
            reason = None if not mismatches else "identity/provenance mismatch: " + ", ".join(mismatches)

        record = ReleaseReconciliationRecord(
            reconciliation_id=reconciliation_id or str(uuid4()),
            dispatch_id=dispatch.dispatch_id,
            outcome_id=outcome_id,
            finalization_fingerprint=dispatch.finalization_fingerprint,
            status=status,
            reason=reason,
            reconciled_at=now or datetime.now(timezone.utc),
        )
        self._records[key] = record
        return record

    def get(self, dispatch_id: str, outcome_id: str | None = None):
        return self._records.get((dispatch_id, outcome_id))
