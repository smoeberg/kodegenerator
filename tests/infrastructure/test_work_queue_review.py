"""WQ-106: review/rejection/rework lifecycle tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_review import WorkQueueReviewService


ORG = "org-review"
NOW = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
ARTIFACT = ImmutableVersionRef(kind="git_commit", value="artifact-v1")


def capability() -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=CapabilityLevel.EXPERT,
        used_by=["worker-a", "worker-b"],
    )


def factory_for(url: str, **connect_args):
    engine = create_engine(url, future=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def add_awaiting(session_factory, *, work_unit_id="wu-review", worker="worker-a") -> None:
    unit = WorkUnit(
        id=work_unit_id,
        title=work_unit_id,
        required_capability=capability(),
        state=WorkUnitState.AWAITING_REVIEW,
        delivered_artifact_version=ARTIFACT,
        previous_worker=worker,
    )
    with session_factory() as session:
        WorkUnitRepository(session).add(ORG, unit)
        session.commit()


def add_rejected(
    session_factory,
    *,
    work_unit_id="wu-review",
    worker="worker-a",
    rework_attempts=0,
) -> None:
    unit = WorkUnit(
        id=work_unit_id,
        title=work_unit_id,
        required_capability=capability(),
        state=WorkUnitState.REJECTED,
        delivered_artifact_version=ARTIFACT,
        previous_worker=worker,
        rework_attempts=rework_attempts,
    )
    with session_factory() as session:
        WorkUnitRepository(session).add(ORG, unit)
        session.commit()


def get_unit(session_factory, work_unit_id="wu-review"):
    with session_factory() as session:
        return WorkUnitRepository(session).get(ORG, work_unit_id)


def history(session_factory, work_unit_id="wu-review"):
    with session_factory() as session:
        return WorkUnitRepository(session).list_history(ORG, work_unit_id)


def service(session_factory):
    return WorkQueueReviewService(
        session_factory,
        organization_id=ORG,
        lease_seconds=60,
        clock=lambda: NOW,
    )


def test_reviewer_rejection_is_rejected_not_failed_and_preserves_artifact() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_awaiting(sf)

    rejected = service(sf).reject(
        "wu-review", reviewer_id="reviewer-1", artifact_version=ARTIFACT
    )

    assert rejected is not None
    assert rejected.state is WorkUnitState.REJECTED
    assert rejected.state is not WorkUnitState.FAILED
    assert rejected.delivered_artifact_version == ARTIFACT
    persisted = get_unit(sf)
    assert persisted.state is WorkUnitState.REJECTED
    assert persisted.delivered_artifact_version == ARTIFACT
    revisions = history(sf)
    assert len(revisions) == 2
    assert revisions[-1].state is WorkUnitState.REJECTED


def test_reviewer_can_approve_exact_artifact() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_awaiting(sf)

    approved = service(sf).approve(
        "wu-review", reviewer_id="reviewer-1", artifact_version=ARTIFACT
    )

    assert approved is not None
    assert approved.state is WorkUnitState.APPROVED
    assert approved.delivered_artifact_version == ARTIFACT
    assert len(history(sf)) == 2


def test_review_is_bound_to_exact_artifact_version() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_awaiting(sf)
    stale = ImmutableVersionRef(kind="git_commit", value="artifact-stale")

    assert service(sf).approve(
        "wu-review", reviewer_id="reviewer-1", artifact_version=stale
    ) is None
    assert get_unit(sf).state is WorkUnitState.AWAITING_REVIEW
    assert len(history(sf)) == 1


def test_worker_cannot_review_own_submission() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_awaiting(sf, worker="worker-a")

    assert service(sf).approve(
        "wu-review", reviewer_id="worker-a", artifact_version=ARTIFACT
    ) is None
    assert get_unit(sf).state is WorkUnitState.AWAITING_REVIEW


def test_prior_worker_gets_first_bounded_rework_preference() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_rejected(sf, worker="worker-a", rework_attempts=0)
    svc = service(sf)

    assert svc.claim_rework("worker-b", [capability()]) is None
    claimed = svc.claim_rework("worker-a", [capability()])

    assert claimed is not None
    assert claimed.state is WorkUnitState.CLAIMED
    assert claimed.claimed_by == "worker-a"
    assert claimed.lease is not None
    assert claimed.lease.worker_id == "worker-a"
    assert claimed.rework_attempts == 1
    assert claimed.delivered_artifact_version is None
    persisted = get_unit(sf)
    assert persisted.delivered_artifact_version is None
    revisions = history(sf)
    assert len(revisions) == 2
    assert revisions[0].delivered_artifact_version == ARTIFACT
    assert revisions[1].delivered_artifact_version is None


def test_rework_preference_can_be_explicitly_overridden() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_rejected(sf, worker="worker-a", rework_attempts=0)

    claimed = service(sf).claim_rework(
        "worker-b", [capability()], allow_preference_override=True
    )

    assert claimed is not None
    assert claimed.claimed_by == "worker-b"
    assert claimed.rework_attempts == 1
    assert claimed.lease.lease_id


def test_after_first_rework_attempt_any_compatible_worker_may_claim() -> None:
    sf = factory_for("sqlite:///:memory:")
    add_rejected(sf, worker="worker-a", rework_attempts=1)

    claimed = service(sf).claim_rework("worker-b", [capability()])

    assert claimed is not None
    assert claimed.claimed_by == "worker-b"
    assert claimed.rework_attempts == 2


def test_ten_concurrent_rework_claimants_elect_exactly_one_owner(tmp_path) -> None:
    db_path = tmp_path / "review-race.sqlite"
    sf = factory_for(
        f"sqlite:///{db_path}",
        check_same_thread=False,
        timeout=30,
    )
    add_rejected(sf, work_unit_id="wu-race", rework_attempts=1)
    barrier = threading.Barrier(10)

    def attempt(index: int):
        barrier.wait(timeout=10)
        return service(sf).claim_rework(f"worker-{index}", [capability()])

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(attempt, index) for index in range(10)]
        results = [future.result(timeout=30) for future in futures]

    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    winner = winners[0]
    persisted = get_unit(sf, "wu-race")
    assert persisted.state is WorkUnitState.CLAIMED
    assert persisted.claimed_by == winner.claimed_by
    assert persisted.lease.lease_id == winner.lease.lease_id
    assert persisted.rework_attempts == 2
    assert len(history(sf, "wu-race")) == 2
