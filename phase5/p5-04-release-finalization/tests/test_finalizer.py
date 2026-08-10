"""P5-04 release-finalization boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from finalization_models import FinalizationDisposition, FinalizationError  # noqa: E402
from finalizer import ReleaseFinalizer  # noqa: E402


class State:
    value = "OUTCOME_MATERIALIZED"


class Value:
    def __init__(self, value):
        self.value = value


class Outcome:
    state = State()
    verifier_id = "p3-20"
    outcome_fingerprint = "outcome-fp"
    handoff_fingerprint = "handoff-fp"
    request_id = "request-1"
    submission_id = "submission-1"
    submission_fingerprint = "submission-fp"
    contract_fingerprint = "contract-fp"
    decision_fingerprint = "decision-fp"

    def __init__(self, value="PASSED"):
        self.value = Value(value)


def test_passed_outcome_becomes_release_eligible():
    record = ReleaseFinalizer().finalize(
        Outcome(), now=datetime(2026, 1, 1, tzinfo=timezone.utc), finalization_id="final-1"
    )
    assert record.disposition is FinalizationDisposition.RELEASE_ELIGIBLE
    assert record.verifier_id == "p3-20"
    assert record.outcome_fingerprint == "outcome-fp"


def test_failed_outcome_is_terminally_release_blocked():
    record = ReleaseFinalizer().finalize(Outcome("FAILED"), finalization_id="final-2")
    assert record.disposition is FinalizationDisposition.RELEASE_BLOCKED


def test_finalization_is_idempotent_for_same_outcome():
    finalizer = ReleaseFinalizer()
    first = finalizer.finalize(Outcome(), finalization_id="first")
    second = finalizer.finalize(Outcome(), finalization_id="second")
    assert second is first
    assert second.finalization_id == "first"


def test_rejects_non_p3_20_authority():
    outcome = Outcome()
    outcome.verifier_id = "agent-1"
    try:
        ReleaseFinalizer().finalize(outcome)
    except FinalizationError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("expected FinalizationError")


def test_rejects_non_materialized_outcome():
    outcome = Outcome()
    outcome.state = type("State", (), {"value": "PENDING"})()
    try:
        ReleaseFinalizer().finalize(outcome)
    except FinalizationError as exc:
        assert "OUTCOME_MATERIALIZED" in str(exc)
    else:
        raise AssertionError("expected FinalizationError")


def test_record_is_immutable():
    record = ReleaseFinalizer().finalize(Outcome())
    try:
        record.release_eligible = True
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("finalization record must be immutable")
