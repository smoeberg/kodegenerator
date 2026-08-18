"""P4-01 replay ledger state machine tests (success-only dedup)."""
from __future__ import annotations

import pytest

from phase4.execution.models import ExecutionResult, ExecutionStatus
from phase4.execution.replay_ledger import (
    ClaimOutcomeKind,
    InMemoryReplayLedger,
    LedgerStatus,
)


def _result(execution_id: str, status: ExecutionStatus) -> ExecutionResult:
    return ExecutionResult(
        execution_id=execution_id,
        request_id="req-1",
        authority_policy_id="policy-1",
        authority_policy_version="1",
        agent_identity="agent-1",
        action="demo.read",
        resource="object/1",
        context_packet_id="ctx-1",
        status=status,
        adapter_id="adapter-1",
        output=(("ok", "1"),) if status is ExecutionStatus.SUCCEEDED else (),
        error=None if status is ExecutionStatus.SUCCEEDED else "boom",
        executed_at="2026-08-18T00:00:00+00:00",
    )


def test_empty_claim_acquires_pending():
    ledger = InMemoryReplayLedger()
    outcome = ledger.try_claim("exec-1", grant_id="g1", request_id="req-1")
    assert outcome.kind is ClaimOutcomeKind.ACQUIRED
    assert outcome.record is not None
    assert outcome.record.status is LedgerStatus.PENDING
    assert ledger.get("exec-1").status is LedgerStatus.PENDING


def test_succeeded_locks_and_replays():
    ledger = InMemoryReplayLedger()
    ledger.try_claim("exec-1")
    result = _result("exec-1", ExecutionStatus.SUCCEEDED)
    ledger.complete_succeeded("exec-1", result)

    again = ledger.try_claim("exec-1")
    assert again.kind is ClaimOutcomeKind.ALREADY_SUCCEEDED
    assert again.record is not None
    assert again.record.result == result


def test_failed_is_retryable():
    ledger = InMemoryReplayLedger()
    ledger.try_claim("exec-1")
    ledger.complete_failed("exec-1", _result("exec-1", ExecutionStatus.FAILED))

    reclaim = ledger.try_claim("exec-1")
    assert reclaim.kind is ClaimOutcomeKind.ACQUIRED
    assert reclaim.record is not None
    assert reclaim.record.status is LedgerStatus.PENDING


def test_concurrent_pending_is_in_flight():
    ledger = InMemoryReplayLedger()
    first = ledger.try_claim("exec-1")
    second = ledger.try_claim("exec-1")
    assert first.kind is ClaimOutcomeKind.ACQUIRED
    assert second.kind is ClaimOutcomeKind.IN_FLIGHT


def test_abandon_retains_row_and_allows_retry():
    ledger = InMemoryReplayLedger()
    ledger.try_claim("exec-1")
    ledger.abandon("exec-1")
    record = ledger.get("exec-1")
    assert record is not None
    assert record.status is LedgerStatus.ABANDONED
    assert ledger.try_claim("exec-1").kind is ClaimOutcomeKind.ACQUIRED


def test_complete_succeeded_requires_pending():
    ledger = InMemoryReplayLedger()
    with pytest.raises(RuntimeError, match="pending"):
        ledger.complete_succeeded("missing", _result("missing", ExecutionStatus.SUCCEEDED))


def test_complete_failed_requires_pending():
    ledger = InMemoryReplayLedger()
    ledger.try_claim("exec-1")
    ledger.complete_succeeded("exec-1", _result("exec-1", ExecutionStatus.SUCCEEDED))
    with pytest.raises(RuntimeError, match="pending"):
        ledger.complete_failed("exec-1", _result("exec-1", ExecutionStatus.FAILED))


def test_empty_execution_id_rejected():
    ledger = InMemoryReplayLedger()
    with pytest.raises(ValueError, match="execution_id"):
        ledger.try_claim("")
