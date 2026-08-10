from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from reconciliation_models import ReconciliationError, ReconciliationStatus
from reconciler import ReleaseReconciler


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def dispatch():
    return SimpleNamespace(
        dispatch_id="dispatch-1",
        finalization_fingerprint="final-1",
        verifier_id="p3-20",
    )


def outcome(**changes):
    data = {
        "outcome_id": "outcome-1",
        "dispatch_id": "dispatch-1",
        "finalization_fingerprint": "final-1",
        "verifier_id": "p3-20",
    }
    data.update(changes)
    return SimpleNamespace(**data)


def test_reconciled_matching_identity():
    record = ReleaseReconciler().reconcile(dispatch(), outcome(), now=NOW)
    assert record.status is ReconciliationStatus.RECONCILED


def test_missing_outcome():
    record = ReleaseReconciler().reconcile(dispatch(), now=NOW)
    assert record.status is ReconciliationStatus.OUTCOME_MISSING
    assert record.outcome_id is None


def test_mismatch_is_observed_not_repaired():
    record = ReleaseReconciler().reconcile(dispatch(), outcome(dispatch_id="other"), now=NOW)
    assert record.status is ReconciliationStatus.MISMATCH
    assert "dispatch_id" in record.reason


def test_upstream_records_are_not_mutated():
    d = dispatch()
    o = outcome()
    ReleaseReconciler().reconcile(d, o, now=NOW)
    assert d.dispatch_id == "dispatch-1"
    assert o.dispatch_id == "dispatch-1"


def test_result_is_immutable():
    record = ReleaseReconciler().reconcile(dispatch(), outcome(), now=NOW)
    with pytest.raises((AttributeError, TypeError)):
        record.status = ReconciliationStatus.MISMATCH


def test_idempotent_same_pair():
    reconciler = ReleaseReconciler()
    first = reconciler.reconcile(dispatch(), outcome(), now=NOW)
    second = reconciler.reconcile(dispatch(), outcome(), now=NOW)
    assert second is first
    assert second.reconciliation_fingerprint == first.reconciliation_fingerprint


def test_non_authoritative_verifier_rejected():
    with pytest.raises(ReconciliationError):
        ReleaseReconciler().reconcile(SimpleNamespace(
            dispatch_id="dispatch-1",
            finalization_fingerprint="final-1",
            verifier_id="other",
        ), outcome(), now=NOW)


def test_incomplete_dispatch_rejected():
    with pytest.raises(ReconciliationError):
        ReleaseReconciler().reconcile(SimpleNamespace(
            dispatch_id="dispatch-1",
            finalization_fingerprint="",
            verifier_id="p3-20",
        ), now=NOW)
