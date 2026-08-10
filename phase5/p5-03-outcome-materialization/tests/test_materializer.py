"""P5-03 outcome materialization boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from materializer import OutcomeMaterializer  # noqa: E402
from models import OutcomeError, OutcomeValue  # noqa: E402


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_handoff(passed=True):
    request = SimpleNamespace(
        request_id="req-1",
        submission_id="sub-1",
        submission_fingerprint="sub-fp",
        contract_fingerprint="contract-fp",
    )
    decision = SimpleNamespace(
        verifier="p3-20",
        submission_id="sub-1",
        submission_fingerprint="sub-fp",
        contract_fingerprint="contract-fp",
        passed=passed,
        decision_fingerprint="decision-fp",
    )
    response = SimpleNamespace(decision=decision, received_at=NOW)
    return SimpleNamespace(
        request=request,
        response=response,
        state="VERIFIED_PASSED" if passed else "VERIFIED_FAILED",
        handoff_fingerprint="handoff-fp",
    )


def test_materializes_p3_20_pass_without_reverification():
    outcome = OutcomeMaterializer().materialize(make_handoff(True), outcome_id="out-1", now=NOW)
    assert outcome.value is OutcomeValue.PASSED
    assert outcome.verifier_id == "p3-20"
    assert outcome.decision_fingerprint == "decision-fp"
    assert outcome.submission_fingerprint == "sub-fp"
    assert outcome.contract_fingerprint == "contract-fp"


def test_materializes_p3_20_failure_as_projection_only():
    outcome = OutcomeMaterializer().materialize(make_handoff(False), outcome_id="out-2", now=NOW)
    assert outcome.value is OutcomeValue.FAILED


def test_materialization_is_idempotent_for_same_handoff():
    materializer = OutcomeMaterializer()
    first = materializer.materialize(make_handoff(True), outcome_id="out-1", now=NOW)
    second = materializer.materialize(make_handoff(True), outcome_id="different", now=NOW)
    assert second is first
    assert second.outcome_fingerprint == first.outcome_fingerprint


def test_rejects_non_final_handoff():
    handoff = make_handoff(True)
    handoff.state = "VERIFICATION_RETURNED"
    try:
        OutcomeMaterializer().materialize(handoff)
    except OutcomeError as exc:
        assert "final" in str(exc)
    else:
        raise AssertionError("expected OutcomeError")


def test_rejects_non_p3_20_decision():
    handoff = make_handoff(True)
    handoff.response.decision.verifier = "other-verifier"
    try:
        OutcomeMaterializer().materialize(handoff)
    except OutcomeError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("expected OutcomeError")


def test_rejects_decision_identity_mismatch():
    handoff = make_handoff(True)
    handoff.response.decision.contract_fingerprint = "wrong-contract"
    try:
        OutcomeMaterializer().materialize(handoff)
    except OutcomeError as exc:
        assert "contract" in str(exc)
    else:
        raise AssertionError("expected OutcomeError")
