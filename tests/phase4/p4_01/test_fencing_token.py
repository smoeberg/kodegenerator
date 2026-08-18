"""Fencing token: zombie complete after reclaim must fail closed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from phase4.execution.models import ExecutionResult, ExecutionStatus
from phase4.execution.replay_ledger import (
    ClaimOutcomeKind,
    InMemoryReplayLedger,
    StaleClaimTokenError,
)


def _ok(eid: str) -> ExecutionResult:
    return ExecutionResult(
        execution_id=eid,
        request_id="r",
        authority_policy_id="p",
        authority_policy_version="1",
        agent_identity="a",
        action="demo.read",
        resource="o/1",
        context_packet_id="c",
        status=ExecutionStatus.SUCCEEDED,
        adapter_id="ad",
        output=(("ok", "1"),),
        error=None,
        executed_at="2026-08-18T00:00:00+00:00",
    )


def test_acquired_claim_includes_fencing_token():
    ledger = InMemoryReplayLedger()
    claim = ledger.try_claim("e1")
    assert claim.kind is ClaimOutcomeKind.ACQUIRED
    assert claim.record is not None
    assert claim.record.fencing_token


def test_complete_with_correct_token_succeeds():
    ledger = InMemoryReplayLedger()
    claim = ledger.try_claim("e1")
    token = claim.record.fencing_token  # type: ignore[union-attr]
    ledger.complete_succeeded("e1", _ok("e1"), fencing_token=token)
    assert ledger.get("e1").status.value == "succeeded"  # type: ignore[union-attr]


def test_zombie_complete_after_reclaim_raises():
    ledger = InMemoryReplayLedger(claim_lease_seconds=10)
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
    first = ledger.try_claim("e1", now=t0)
    old_token = first.record.fencing_token  # type: ignore[union-attr]

    second = ledger.try_claim("e1", now=t0 + timedelta(seconds=11))
    assert second.kind is ClaimOutcomeKind.ACQUIRED
    new_token = second.record.fencing_token  # type: ignore[union-attr]
    assert new_token != old_token

    with pytest.raises(StaleClaimTokenError):
        ledger.complete_succeeded("e1", _ok("e1"), fencing_token=old_token)

    ledger.complete_succeeded("e1", _ok("e1"), fencing_token=new_token)
