"""WQ-105: lease renewal, expiry recovery, and fenced submission tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState, WorkerLease
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_lease import WorkQueueLeaseService


ORG = "org-lease"
NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def capability() -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=CapabilityLevel.EXPERT,
        used_by=["worker-old", "worker-new"],
    )


def factory_for(url: str, **connect_args):
    engine = create_engine(url, future=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def add_claimed(
    session_factory,
    *,
    work_unit_id: str = "wu-lease",
    worker_id: str = "worker-old",
    lease_id: str = "lease-old",
    expires_at: datetime,
) -> None:
    lease = WorkerLease(
        lease_id=lease_id,
        worker_id=worker_id,
        claimed_at=NOW - timedelta(minutes=5),
        expires_at=expires_at,
    )
    unit = WorkUnit(
        id=work_unit_id,
        title=work_unit_id,
        required_capability=capability(),
        state=WorkUnitState.CLAIMED,
        claimed_by=worker_id,
        lease=lease,
    )
    with session_factory() as session:
        WorkUnitRepository(session).add(ORG, unit)
        session.commit()


def get_unit(session_factory, work_unit_id="wu-lease"):
    with session_factory() as session:
        return WorkUnitRepository(session).get(ORG, work_unit_id)


def history(session_factory, work_unit_id="wu-lease"):
    with session_factory() as session:
        return WorkUnitRepository(session).list_history(ORG, work_unit_id)


def service(session_factory, *, worker_seconds=60):
    return WorkQueueLeaseService(
        session_factory,
        organization_id=ORG,
        lease_seconds=worker_seconds,
        clock=lambda: NOW,
    )


def test_active_lease_cannot_be_stolen() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW + timedelta(seconds=30))

    recovered = service(sf).recover_next_expired("worker-new", [capability()])

    assert recovered is None
    persisted = get_unit(sf)
    assert persisted.claimed_by == "worker-old"
    assert persisted.lease.lease_id == "lease-old"
    assert len(history(sf)) == 1


def test_expired_lease_is_recovered_with_new_fencing_token() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW - timedelta(seconds=1))

    recovered = service(sf).recover_next_expired("worker-new", [capability()])

    assert recovered is not None
    assert recovered.state is WorkUnitState.CLAIMED
    assert recovered.claimed_by == "worker-new"
    assert recovered.previous_worker == "worker-old"
    assert recovered.lease.worker_id == "worker-new"
    assert recovered.lease.lease_id != "lease-old"
    assert recovered.lease.claimed_at == NOW
    assert recovered.lease.expires_at == NOW + timedelta(seconds=60)
    assert len(history(sf)) == 2


def test_stale_old_lease_token_cannot_submit_after_recovery() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW - timedelta(seconds=1))
    svc = service(sf)
    recovered = svc.recover_next_expired("worker-new", [capability()])
    assert recovered is not None

    stale = svc.submit_for_review(
        "wu-lease",
        worker_id="worker-old",
        lease_id="lease-old",
        delivered_artifact_version=ImmutableVersionRef(kind="git_commit", value="old-artifact"),
    )

    assert stale is None
    persisted = get_unit(sf)
    assert persisted.state is WorkUnitState.CLAIMED
    assert persisted.claimed_by == "worker-new"
    assert persisted.delivered_artifact_version is None
    assert len(history(sf)) == 2


def test_heartbeat_extends_active_lease_without_rotating_token() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW + timedelta(seconds=5))

    renewed = service(sf, worker_seconds=90).heartbeat(
        "wu-lease", worker_id="worker-old", lease_id="lease-old"
    )

    assert renewed is not None
    assert renewed.lease.lease_id == "lease-old"
    assert renewed.lease.expires_at == NOW + timedelta(seconds=90)
    assert len(history(sf)) == 2
    assert service(sf).heartbeat(
        "wu-lease", worker_id="worker-old", lease_id="wrong-token"
    ) is None
    assert len(history(sf)) == 2


def test_submit_for_review_is_fenced_and_clears_active_ownership() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW + timedelta(seconds=30))
    version = ImmutableVersionRef(kind="git_commit", value="artifact-1")

    submitted = service(sf).submit_for_review(
        "wu-lease",
        worker_id="worker-old",
        lease_id="lease-old",
        delivered_artifact_version=version,
    )

    assert submitted is not None
    assert submitted.state is WorkUnitState.AWAITING_REVIEW
    assert submitted.claimed_by is None
    assert submitted.lease is None
    assert submitted.previous_worker == "worker-old"
    assert submitted.delivered_artifact_version == version
    persisted = get_unit(sf)
    assert persisted.state is WorkUnitState.AWAITING_REVIEW
    assert persisted.lease is None
    assert len(history(sf)) == 2


def test_expired_lease_cannot_submit() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_claimed(sf, expires_at=NOW - timedelta(seconds=1))

    submitted = service(sf).submit_for_review(
        "wu-lease",
        worker_id="worker-old",
        lease_id="lease-old",
        delivered_artifact_version=ImmutableVersionRef(kind="git_commit", value="artifact-1"),
    )

    assert submitted is None
    assert get_unit(sf).state is WorkUnitState.CLAIMED
    assert len(history(sf)) == 1


def test_ten_concurrent_recovery_workers_elect_exactly_one_owner(tmp_path) -> None:
    db_path = tmp_path / "lease-race.sqlite"
    sf = factory_for(
        f"sqlite:///{db_path}",
        check_same_thread=False,
        timeout=30,
    )
    add_claimed(sf, work_unit_id="wu-race", expires_at=NOW - timedelta(seconds=1))
    barrier = threading.Barrier(10)

    def attempt(index: int):
        barrier.wait(timeout=10)
        return service(sf).recover_next_expired(f"worker-{index}", [capability()])

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(attempt, index) for index in range(10)]
        results = [future.result(timeout=30) for future in futures]

    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    winner = winners[0]
    persisted = get_unit(sf, "wu-race")
    assert persisted.claimed_by == winner.claimed_by
    assert persisted.lease.lease_id == winner.lease.lease_id
    assert persisted.previous_worker == "worker-old"
    revisions = history(sf, "wu-race")
    assert len(revisions) == 2
    assert revisions[-1].claimed_by == winner.claimed_by
