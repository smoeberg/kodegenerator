"""P4-01 claim lease expiry — RA-3 crash-under-adapter recovery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.execution.durable_ledger import (
    ExecutionReplayLedgerModel,
    SqlAlchemyReplayLedger,
)
from phase4.execution.replay_ledger import (
    ClaimOutcomeKind,
    InMemoryReplayLedger,
    LedgerStatus,
)


def test_live_pending_is_in_flight_within_lease():
    ledger = InMemoryReplayLedger(claim_lease_seconds=60)
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
    first = ledger.try_claim("e1", now=t0)
    assert first.kind is ClaimOutcomeKind.ACQUIRED
    assert first.record is not None
    assert first.record.lease_expires_at == t0 + timedelta(seconds=60)

    second = ledger.try_claim("e1", now=t0 + timedelta(seconds=30))
    assert second.kind is ClaimOutcomeKind.IN_FLIGHT


def test_expired_pending_is_reclaimed():
    ledger = InMemoryReplayLedger(claim_lease_seconds=60)
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
    ledger.try_claim("e1", now=t0)

    # Simulate crash: lease elapsed, no complete_*
    reclaimed = ledger.try_claim("e1", now=t0 + timedelta(seconds=61))
    assert reclaimed.kind is ClaimOutcomeKind.ACQUIRED
    assert reclaimed.record is not None
    assert reclaimed.record.status is LedgerStatus.PENDING
    assert reclaimed.record.lease_expires_at == t0 + timedelta(seconds=121)


def test_durable_expired_pending_reclaim():
    engine = create_engine("sqlite:///:memory:", future=True)
    assert ExecutionReplayLedgerModel.__tablename__ == "execution_replay_ledger"
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    ledger = SqlAlchemyReplayLedger(
        sessions,
        organization_id="org-test",
        claim_lease_seconds=30,
    )

    t0 = datetime(2026, 8, 18, 15, 0, 0, tzinfo=timezone.utc)
    assert ledger.try_claim("crash-1", now=t0).kind is ClaimOutcomeKind.ACQUIRED
    assert (
        ledger.try_claim("crash-1", now=t0 + timedelta(seconds=10)).kind
        is ClaimOutcomeKind.IN_FLIGHT
    )
    assert (
        ledger.try_claim("crash-1", now=t0 + timedelta(seconds=31)).kind
        is ClaimOutcomeKind.ACQUIRED
    )


def test_lease_boundary_is_exclusive_at_expiry_instant():
    """now >= lease_expires_at → expired (exclusive live window)."""
    ledger = InMemoryReplayLedger(claim_lease_seconds=10)
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
    ledger.try_claim("e1", now=t0)
    at_expiry = t0 + timedelta(seconds=10)
    assert ledger.try_claim("e1", now=at_expiry).kind is ClaimOutcomeKind.ACQUIRED
