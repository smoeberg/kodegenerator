"""P5-05 release-dispatch boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parent
sys.path.insert(0, str(SLICE))

from dispatch_models import DispatchError, DispatchState  # noqa: E402
from dispatcher import ReleaseDispatcher  # noqa: E402


class State:
    value = "FINALIZED"


class Disposition:
    value = "RELEASE_ELIGIBLE"


class Finalization:
    finalization_fingerprint = "finalization-fp"
    outcome_fingerprint = "outcome-fp"
    handoff_fingerprint = "handoff-fp"
    request_id = "request-1"
    submission_id = "submission-1"
    submission_fingerprint = "submission-fp"
    contract_fingerprint = "contract-fp"
    decision_fingerprint = "decision-fp"
    verifier_id = "p3-20"
    outcome_value = "PASSED"
    state = State()
    disposition = Disposition()


class BlockedFinalization(Finalization):
    disposition = type("Disposition", (), {"value": "RELEASE_BLOCKED"})()
    outcome_value = "FAILED"


def test_eligible_finalization_is_dispatched():
    record = ReleaseDispatcher().dispatch(
        Finalization(),
        dispatch_id="dispatch-1",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert record.state is DispatchState.DISPATCHED
    assert record.dispatch_id == "dispatch-1"
    assert record.finalization_fingerprint == "finalization-fp"
    assert record.outcome_fingerprint == "outcome-fp"
    assert record.verifier_id == "p3-20"


def test_blocked_finalization_is_never_dispatched():
    try:
        ReleaseDispatcher().dispatch(BlockedFinalization())
    except DispatchError as exc:
        assert "RELEASE_ELIGIBLE" in str(exc)
    else:
        raise AssertionError("expected DispatchError")


def test_dispatch_is_idempotent_for_same_finalization():
    dispatcher = ReleaseDispatcher()
    first = dispatcher.dispatch(Finalization(), dispatch_id="first")
    second = dispatcher.dispatch(Finalization(), dispatch_id="second")
    assert second is first
    assert second.dispatch_id == "first"


def test_sink_receives_immutable_dispatch_record_once():
    received = []

    def sink(record):
        received.append(record)

    dispatcher = ReleaseDispatcher()
    first = dispatcher.dispatch(Finalization(), sink=sink)
    second = dispatcher.dispatch(Finalization(), sink=sink)

    assert received == [first]
    assert second is first
    try:
        first.dispatch_id = "changed"
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("dispatch record must be immutable")


def test_rejects_non_p3_20_authority():
    finalization = Finalization()
    finalization.verifier_id = "agent-1"
    try:
        ReleaseDispatcher().dispatch(finalization)
    except DispatchError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("expected DispatchError")


def test_rejects_non_finalized_state():
    finalization = Finalization()
    finalization.state = type("State", (), {"value": "PENDING"})()
    try:
        ReleaseDispatcher().dispatch(finalization)
    except DispatchError as exc:
        assert "FINALIZED" in str(exc)
    else:
        raise AssertionError("expected DispatchError")


def test_preserves_complete_upstream_identity_chain():
    record = ReleaseDispatcher().dispatch(Finalization())
    assert record.handoff_fingerprint == "handoff-fp"
    assert record.request_id == "request-1"
    assert record.submission_id == "submission-1"
    assert record.submission_fingerprint == "submission-fp"
    assert record.contract_fingerprint == "contract-fp"
    assert record.decision_fingerprint == "decision-fp"
