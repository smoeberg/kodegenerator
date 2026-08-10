"""P5-06 release outcome boundary tests."""
from __future__ import annotations

from datetime import datetime, timezone

from p5_06_release_outcome_models import ReleaseOutcomeError, ReleaseOutcomeStatus
from outcome_recorder import ReleaseOutcomeRecorder


class State:
    value = "DISPATCHED"


class Dispatch:
    dispatch_id = "dispatch-1"
    finalization_fingerprint = "finalization-fp"
    outcome_fingerprint = "outcome-fp"
    verifier_id = "p3-20"
    state = State()


def test_records_accepted_outcome_and_preserves_provenance():
    record = ReleaseOutcomeRecorder().record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="provider-event-1", release_reference="release-42", outcome_id="outcome-1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert record.dispatch_id == "dispatch-1"
    assert record.finalization_fingerprint == "finalization-fp"
    assert record.outcome_fingerprint == "outcome-fp"
    assert record.verifier_id == "p3-20"
    assert record.status is ReleaseOutcomeStatus.RELEASE_ACCEPTED


def test_records_rejected_and_failed_outcomes():
    recorder = ReleaseOutcomeRecorder()
    rejected = recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_REJECTED, external_reference="provider-reject", release_reference="release-r")
    failed_dispatch = type("Dispatch", (), {**Dispatch.__dict__, "dispatch_id": "dispatch-2"})()
    failed = recorder.record(failed_dispatch, status=ReleaseOutcomeStatus.RELEASE_FAILED, external_reference="provider-fail", release_reference="release-f")
    assert rejected.status is ReleaseOutcomeStatus.RELEASE_REJECTED
    assert failed.status is ReleaseOutcomeStatus.RELEASE_FAILED


def test_same_dispatch_and_external_reference_is_idempotent():
    recorder = ReleaseOutcomeRecorder()
    first = recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="provider-event", release_reference="release-1", outcome_id="first")
    second = recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="provider-event", release_reference="release-1", outcome_id="second")
    assert second is first
    assert second.outcome_id == "first"


def test_conflicting_duplicate_is_rejected():
    recorder = ReleaseOutcomeRecorder()
    recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="provider-event", release_reference="release-1")
    try:
        recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_FAILED, external_reference="provider-event", release_reference="release-1")
    except ReleaseOutcomeError as exc:
        assert "conflicting" in str(exc)
    else:
        raise AssertionError("expected conflicting outcome rejection")


def test_dispatch_without_p3_20_is_rejected():
    dispatch = type("Dispatch", (), {**Dispatch.__dict__, "verifier_id": "agent-1"})()
    try:
        ReleaseOutcomeRecorder().record(dispatch, status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="event", release_reference="release")
    except ReleaseOutcomeError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("expected authority rejection")


def test_blocked_or_non_dispatch_state_is_rejected():
    dispatch = type("Dispatch", (), {**Dispatch.__dict__, "state": type("State", (), {"value": "BLOCKED"})()})()
    try:
        ReleaseOutcomeRecorder().record(dispatch, status=ReleaseOutcomeStatus.RELEASE_FAILED, external_reference="event", release_reference="release")
    except ReleaseOutcomeError as exc:
        assert "DISPATCHED" in str(exc)
    else:
        raise AssertionError("expected state rejection")


def test_record_is_immutable_and_serialization_is_deterministic():
    record = ReleaseOutcomeRecorder().record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="event", release_reference="release", outcome_id="outcome-1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert record.canonical_json() == record.canonical_json()
    try:
        record.status = ReleaseOutcomeStatus.RELEASE_FAILED
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("outcome record must be immutable")


def test_sink_receives_record_once():
    received = []
    recorder = ReleaseOutcomeRecorder()
    first = recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="event", release_reference="release", sink=received.append)
    recorder.record(Dispatch(), status=ReleaseOutcomeStatus.RELEASE_ACCEPTED, external_reference="event", release_reference="release", sink=received.append)
    assert received == [first]
