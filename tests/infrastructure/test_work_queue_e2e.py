"""WQ-108: end-to-end proof for Work Queue v0.

This test intentionally adds no new runtime abstraction.  It composes the
approved Work Queue v0 boundaries and proves the lifecycle as one integrated
flow:

    dependency approval
    -> deterministic readiness
    -> atomic claim with exact dependency snapshot
    -> lease expiry / recovery with fencing
    -> submission
    -> independent review rejection
    -> bounded atomic rework
    -> resubmission
    -> approval
    -> passive metrics + append-only provenance
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue import WorkQueueClaimService
from infrastructure.runtime.work_queue_lease import WorkQueueLeaseService
from infrastructure.runtime.work_queue_metrics import WorkQueueMetrics, WorkQueueMetricsService
from infrastructure.runtime.work_queue_review import WorkQueueReviewService


ORG = "org-wq-108"
CREATED = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
APPROVED_AT = datetime(2020, 1, 1, 12, 1, tzinfo=timezone.utc)
RECOVERY_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
UPSTREAM_VERSION = ImmutableVersionRef(kind="git_commit", value="upstream-v1")
ARTIFACT_V1 = ImmutableVersionRef(kind="git_commit", value="artifact-v1")
ARTIFACT_V2 = ImmutableVersionRef(kind="git_commit", value="artifact-v2")


def capability() -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=CapabilityLevel.EXPERT,
        used_by=["worker-a", "worker-b"],
    )


def factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def add(sf, unit: WorkUnit) -> None:
    with sf() as session:
        WorkUnitRepository(session).add(ORG, unit)
        session.commit()


def get(sf, work_unit_id: str) -> WorkUnit:
    with sf() as session:
        unit = WorkUnitRepository(session).get(ORG, work_unit_id)
        assert unit is not None
        return unit


def history(sf, work_unit_id: str):
    with sf() as session:
        return WorkUnitRepository(session).list_history(ORG, work_unit_id)


def approve_upstream(sf) -> None:
    with sf() as session:
        repo = WorkUnitRepository(session)
        upstream = repo.get(ORG, "upstream")
        assert upstream is not None
        repo.update(
            ORG,
            replace(
                upstream,
                state=WorkUnitState.APPROVED,
                delivered_artifact_version=UPSTREAM_VERSION,
                updated_at=APPROVED_AT,
            ),
        )
        session.commit()


def test_work_queue_v0_end_to_end_proof() -> None:
    sf = factory()
    cap = capability()
    metrics = WorkQueueMetrics()
    metric_service = WorkQueueMetricsService(sf, organization_id=ORG, metrics=metrics)

    # Start with an unresolved dependency: downstream is PENDING but not ready.
    add(
        sf,
        WorkUnit(
            id="upstream",
            title="upstream",
            required_capability=cap,
            state=WorkUnitState.PENDING,
            created_at=CREATED,
            updated_at=CREATED,
        ),
    )
    add(
        sf,
        WorkUnit(
            id="downstream",
            title="downstream",
            required_capability=cap,
            depends_on=("upstream",),
            created_at=CREATED,
            updated_at=CREATED,
        ),
    )

    claim_service = WorkQueueClaimService(sf, organization_id=ORG, lease_seconds=60)
    assert metric_service.snapshot().ready_queue_depth == 0
    assert claim_service.claim_next_ready("worker-a", [cap]) is None
    assert get(sf, "downstream").state is WorkUnitState.PENDING

    # Approval plus an immutable delivered version makes the dependency claimable.
    approve_upstream(sf)
    assert metric_service.snapshot().ready_queue_depth == 1

    claimed = claim_service.claim_next_ready("worker-a", [cap])
    metrics.record_claim(latency_seconds=0.01, conflict=False)
    assert claimed is not None
    assert claimed.state is WorkUnitState.CLAIMED
    assert claimed.claimed_by == "worker-a"
    assert claimed.lease is not None
    assert len(claimed.depends_on_snapshot) == 1
    assert claimed.depends_on_snapshot[0].work_unit_id == "upstream"
    assert claimed.depends_on_snapshot[0].version == UPSTREAM_VERSION
    stale_lease_id = claimed.lease.lease_id

    # Move the clock past the original lease.  A new worker recovers ownership
    # with a different fencing token; the stale owner cannot submit afterwards.
    lease_service = WorkQueueLeaseService(
        sf,
        organization_id=ORG,
        lease_seconds=60,
        clock=lambda: RECOVERY_TIME,
    )
    recovered = lease_service.recover_next_expired("worker-b", [cap])
    metrics.record_lease_expiry()
    assert recovered is not None
    assert recovered.state is WorkUnitState.CLAIMED
    assert recovered.previous_worker == "worker-a"
    assert recovered.claimed_by == "worker-b"
    assert recovered.lease is not None
    assert recovered.lease.lease_id != stale_lease_id
    assert recovered.depends_on_snapshot[0].version == UPSTREAM_VERSION

    assert (
        lease_service.submit_for_review(
            "downstream",
            worker_id="worker-a",
            lease_id=stale_lease_id,
            delivered_artifact_version=ARTIFACT_V1,
        )
        is None
    )
    assert get(sf, "downstream").state is WorkUnitState.CLAIMED

    submitted_v1 = lease_service.submit_for_review(
        "downstream",
        worker_id="worker-b",
        lease_id=recovered.lease.lease_id,
        delivered_artifact_version=ARTIFACT_V1,
    )
    metrics.record_worker_busy(12)
    metrics.record_worker_idle(3)
    metrics.record_execution(12)
    metrics.record_review_wait(2)
    assert submitted_v1 is not None
    assert submitted_v1.state is WorkUnitState.AWAITING_REVIEW
    assert submitted_v1.claimed_by is None
    assert submitted_v1.lease is None
    assert submitted_v1.delivered_artifact_version == ARTIFACT_V1
    assert metric_service.snapshot().review_queue_depth == 1

    review_service = WorkQueueReviewService(
        sf,
        organization_id=ORG,
        lease_seconds=60,
        clock=lambda: RECOVERY_TIME,
    )
    rejected = review_service.reject(
        "downstream",
        reviewer_id="reviewer-1",
        artifact_version=ARTIFACT_V1,
    )
    metrics.record_review(duration_seconds=1, rejected=True)
    assert rejected is not None
    assert rejected.state is WorkUnitState.REJECTED
    assert rejected.state is not WorkUnitState.FAILED
    assert rejected.delivered_artifact_version == ARTIFACT_V1

    # First bounded rework attempt prefers the previous execution worker.
    assert review_service.claim_rework("worker-a", [cap]) is None
    rework = review_service.claim_rework("worker-b", [cap])
    metrics.record_rework()
    assert rework is not None
    assert rework.state is WorkUnitState.CLAIMED
    assert rework.claimed_by == "worker-b"
    assert rework.rework_attempts == 1
    assert rework.delivered_artifact_version is None
    assert rework.lease is not None
    assert rework.depends_on_snapshot[0].version == UPSTREAM_VERSION

    submitted_v2 = lease_service.submit_for_review(
        "downstream",
        worker_id="worker-b",
        lease_id=rework.lease.lease_id,
        delivered_artifact_version=ARTIFACT_V2,
    )
    metrics.record_execution(5)
    metrics.record_review_wait(1)
    assert submitted_v2 is not None
    assert submitted_v2.state is WorkUnitState.AWAITING_REVIEW
    assert submitted_v2.delivered_artifact_version == ARTIFACT_V2

    approved = review_service.approve(
        "downstream",
        reviewer_id="reviewer-1",
        artifact_version=ARTIFACT_V2,
    )
    metrics.record_review(duration_seconds=1, rejected=False)
    assert approved is not None
    assert approved.state is WorkUnitState.APPROVED
    assert approved.delivered_artifact_version == ARTIFACT_V2
    assert approved.depends_on_snapshot[0].version == UPSTREAM_VERSION

    # The current projection is terminally approved, while provenance retains
    # the rejected artifact and every successful lifecycle transition.
    revisions = history(sf, "downstream")
    assert [revision.state for revision in revisions] == [
        WorkUnitState.PENDING,
        WorkUnitState.CLAIMED,
        WorkUnitState.CLAIMED,
        WorkUnitState.AWAITING_REVIEW,
        WorkUnitState.REJECTED,
        WorkUnitState.CLAIMED,
        WorkUnitState.AWAITING_REVIEW,
        WorkUnitState.APPROVED,
    ]
    assert revisions[4].delivered_artifact_version == ARTIFACT_V1
    assert revisions[5].delivered_artifact_version is None
    assert revisions[-1].delivered_artifact_version == ARTIFACT_V2
    assert all(
        not revision.depends_on_snapshot
        or revision.depends_on_snapshot[0].version == UPSTREAM_VERSION
        for revision in revisions
    )

    before_metrics_history = len(revisions)
    snapshot = metric_service.snapshot()
    assert snapshot.queue_depth == 0
    assert snapshot.ready_queue_depth == 0
    assert snapshot.review_queue_depth == 0
    assert snapshot.lease_expiry_count == 1
    assert snapshot.rejection_rate == 0.5
    assert snapshot.rework_rate == 1.0
    assert snapshot.claim_latency == 0.01
    assert snapshot.worker_utilization == 0.8
    assert snapshot.execution_duration == 8.5
    assert snapshot.review_wait_time == 1.5
    assert snapshot.review_duration == 1.0
    assert len(history(sf, "downstream")) == before_metrics_history
