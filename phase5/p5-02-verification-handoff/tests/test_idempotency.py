"""P5-02 idempotency tests."""

import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from handoff import VerificationHandoffEngine  # noqa: E402
from test_handoff import fixture  # noqa: E402


def test_same_subject_reuses_request_identity():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events, request_id="first")
    repeat = engine.prepare(contract, submission, lifecycle_events=events, request_id="second")
    assert request.request_id == "first"
    assert repeat.request_id == "first"
    assert request.request_fingerprint == repeat.request_fingerprint
    assert len(engine.events(request)) == 1


def test_changed_submission_fingerprint_is_new_subject():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    first = engine.prepare(contract, submission, lifecycle_events=events)
    object.__setattr__(submission, "submission_fingerprint", "new-submission-fingerprint")
    second = engine.prepare(contract, submission, lifecycle_events=events)
    assert first.request_id != second.request_id
    assert first.request_fingerprint != second.request_fingerprint
