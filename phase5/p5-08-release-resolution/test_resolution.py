from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from resolution_models import (
    ReleaseResolutionRecord,
    ResolutionDisposition,
    ResolutionError,
    ResolutionPolicy,
)
from resolver import ReleaseResolver


NOW = datetime(2026, 8, 11, 6, 45, tzinfo=timezone.utc)


def dispatch(**changes):
    data = {
        "dispatch_id": "dispatch-1",
        "finalization_fingerprint": "final-1",
        "verifier_id": "p3-20",
        "release_id": "release-1",
    }
    data.update(changes)
    return SimpleNamespace(**data)


def outcome(**changes):
    data = {
        "outcome_id": "outcome-1",
        "dispatch_id": "dispatch-1",
        "finalization_fingerprint": "final-1",
        "verifier_id": "p3-20",
        "release_id": "release-1",
        "accepted": True,
    }
    data.update(changes)
    return SimpleNamespace(**data)


def reconciliation(status="RECONCILED", **changes):
    data = {
        "reconciliation_id": "reconciliation-1",
        "dispatch_id": "dispatch-1",
        "outcome_id": "outcome-1",
        "finalization_fingerprint": "final-1",
        "status": status,
        "reason": None,
        "reconciliation_fingerprint": "recon-fingerprint-1",
    }
    if status == "OUTCOME_MISSING":
        data["outcome_id"] = None
    data.update(changes)
    return SimpleNamespace(**data)


def test_reconciled_accepted_outcome_resolves_to_no_action():
    record = ReleaseResolver().resolve(
        reconciliation(),
        dispatch(),
        outcome(),
        policy=ResolutionPolicy(),
        now=NOW,
    )

    assert record.disposition is ResolutionDisposition.NO_ACTION


def test_outcome_missing_without_explicit_retry_policy_fails_closed():
    with pytest.raises(ResolutionError):
        ReleaseResolver().resolve(
            reconciliation("OUTCOME_MISSING"),
            dispatch(),
            outcome=None,
            now=NOW,
        )


def test_outcome_missing_with_explicit_retry_policy_requests_retry():
    policy = ResolutionPolicy(outcome_missing=ResolutionDisposition.RETRY_REQUESTED)

    record = ReleaseResolver().resolve(
        reconciliation("OUTCOME_MISSING"),
        dispatch(),
        outcome=None,
        policy=policy,
        now=NOW,
    )

    assert record.disposition is ResolutionDisposition.RETRY_REQUESTED


def test_mismatch_without_policy_fails_closed_to_safe_supervisory_boundary():
    record = ReleaseResolver().resolve(
        reconciliation("MISMATCH", reason="identity/provenance mismatch: dispatch_id"),
        dispatch(),
        outcome(dispatch_id="other"),
        now=NOW,
    )

    assert record.disposition in {
        ResolutionDisposition.ESCALATION_REQUIRED,
        ResolutionDisposition.RELEASE_BLOCKED,
    }
    assert record.disposition is not ResolutionDisposition.RETRY_REQUESTED


def test_mismatch_policy_can_explicitly_block_release():
    policy = ResolutionPolicy(mismatch=ResolutionDisposition.RELEASE_BLOCKED)

    record = ReleaseResolver().resolve(
        reconciliation("MISMATCH", reason="identity/provenance mismatch: dispatch_id"),
        dispatch(),
        outcome(dispatch_id="other"),
        policy=policy,
        now=NOW,
    )

    assert record.disposition is ResolutionDisposition.RELEASE_BLOCKED


def test_unknown_reconciliation_status_fails_closed():
    with pytest.raises(ResolutionError):
        ReleaseResolver().resolve(
            reconciliation("UNKNOWN"),
            dispatch(),
            outcome(),
            policy=ResolutionPolicy(),
            now=NOW,
        )


def test_conflicting_dispatch_identity_fails_closed():
    with pytest.raises(ResolutionError):
        ReleaseResolver().resolve(
            reconciliation(),
            dispatch(dispatch_id="other"),
            outcome(),
            policy=ResolutionPolicy(),
            now=NOW,
        )


def test_conflicting_finalization_provenance_fails_closed():
    with pytest.raises(ResolutionError):
        ReleaseResolver().resolve(
            reconciliation(finalization_fingerprint="other-final"),
            dispatch(),
            outcome(),
            policy=ResolutionPolicy(),
            now=NOW,
        )


def test_missing_authoritative_verifier_provenance_fails_closed():
    with pytest.raises(ResolutionError):
        ReleaseResolver().resolve(
            reconciliation(),
            dispatch(verifier_id=""),
            outcome(),
            policy=ResolutionPolicy(),
            now=NOW,
        )


def test_resolution_preserves_reconciliation_fingerprint_and_identity_chain():
    record = ReleaseResolver().resolve(
        reconciliation(),
        dispatch(),
        outcome(),
        policy=ResolutionPolicy(),
        now=NOW,
    )

    assert record.reconciliation_fingerprint == "recon-fingerprint-1"
    assert record.dispatch_id == "dispatch-1"
    assert record.outcome_id == "outcome-1"
    assert record.finalization_fingerprint == "final-1"
    assert record.verifier_id == "p3-20"
    assert record.release_id == "release-1"


def test_resolution_record_is_immutable():
    record = ReleaseResolver().resolve(
        reconciliation(),
        dispatch(),
        outcome(),
        policy=ResolutionPolicy(),
        now=NOW,
    )

    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        record.disposition = ResolutionDisposition.RELEASE_BLOCKED


def test_same_inputs_and_policy_are_deterministic():
    policy = ResolutionPolicy()
    first = ReleaseResolver().resolve(
        reconciliation(), dispatch(), outcome(), policy=policy, now=NOW
    )
    second = ReleaseResolver().resolve(
        reconciliation(), dispatch(), outcome(), policy=policy, now=NOW
    )

    assert first.fingerprint == second.fingerprint
    assert first == second


def test_upstream_records_are_not_mutated():
    d = dispatch()
    o = outcome()
    r = reconciliation()

    ReleaseResolver().resolve(r, d, o, policy=ResolutionPolicy(), now=NOW)

    assert d.dispatch_id == "dispatch-1"
    assert o.dispatch_id == "dispatch-1"
    assert r.status == "RECONCILED"


def test_resolution_does_not_create_execution_side_effects():
    resolver = ReleaseResolver()
    record = resolver.resolve(
        reconciliation(),
        dispatch(),
        outcome(),
        policy=ResolutionPolicy(),
        now=NOW,
    )

    assert record.disposition is ResolutionDisposition.NO_ACTION
    assert not hasattr(resolver, "execute")
    assert not hasattr(resolver, "retry")
    assert not hasattr(resolver, "dispatch")
