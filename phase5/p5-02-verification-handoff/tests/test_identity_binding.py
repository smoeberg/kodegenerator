"""P5-02 identity and authority binding tests."""

from datetime import datetime, timezone
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from handoff import VerificationHandoffEngine  # noqa: E402
from models import HandoffError, VerificationResponse  # noqa: E402
from p5_02_loader import load_p5_00  # noqa: E402
from test_handoff import fixture, decision  # noqa: E402

p5 = load_p5_00()


def test_contract_fingerprint_mismatch_is_rejected():
    contract, submission, events = fixture()
    other, _, _ = fixture(contract_id="different-contract")
    engine = VerificationHandoffEngine()
    try:
        engine.prepare(other, submission, lifecycle_events=events)
    except HandoffError as exc:
        assert "contract fingerprint" in str(exc)
    else:
        raise AssertionError("expected contract binding rejection")


def test_decision_contract_fingerprint_mismatch_is_rejected():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events)
    bad = decision(contract, submission)
    object.__setattr__(bad, "contract_fingerprint", "wrong-contract")
    try:
        engine.bind_response(request, VerificationResponse(bad, datetime.now(timezone.utc)))
    except HandoffError as exc:
        assert "contract fingerprint mismatch" in str(exc)
    else:
        raise AssertionError("expected decision contract rejection")


def test_p5_02_has_no_verification_decision_factory():
    assert not hasattr(VerificationHandoffEngine, "verify")
    assert not hasattr(VerificationHandoffEngine, "create_decision")
