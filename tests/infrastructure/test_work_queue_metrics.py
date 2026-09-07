"""WQ-107: passive Work Queue observability tests."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_metrics import WorkQueueMetrics, WorkQueueMetricsService


ORG = "org-metrics"
OTHER = "org-other"


def capability() -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=CapabilityLevel.EXPERT,
    )


def factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def add(sf, organization_id: str, unit: WorkUnit) -> None:
    with sf() as session:
        WorkUnitRepository(session).add(organization_id, unit)
        session.commit()


def history(sf, organization_id: str, work_unit_id: str):
    with sf() as session:
        return WorkUnitRepository(session).list_history(organization_id, work_unit_id)


def test_empty_snapshot_is_zeroed() -> None:
    sf = factory()

    snapshot = WorkQueueMetricsService(sf, organization_id=ORG).snapshot()

    assert snapshot.queue_depth == 0
    assert snapshot.ready_queue_depth == 0
    assert snapshot.review_queue_depth == 0
    assert snapshot.claim_latency == 0.0
    assert snapshot.claim_conflict_rate == 0.0
    assert snapshot.worker_utilization == 0.0
    assert snapshot.rejection_rate == 0.0
    assert snapshot.rework_rate == 0.0
    assert snapshot.lease_expiry_count == 0


def test_queue_gauges_are_derived_from_durable_projection() -> None:
    sf = factory()
    upstream = WorkUnit(
        id="upstream",
        title="upstream",
        required_capability=capability(),
        state=WorkUnitState.APPROVED,
        delivered_artifact_version=ImmutableVersionRef(kind="git_commit", value="up-v1"),
    )
    ready = WorkUnit(
        id="ready",
        title="ready",
        required_capability=capability(),
        state=WorkUnitState.PENDING,
        depends_on=("upstream",),
    )
    review = WorkUnit(
        id="review",
        title="review",
        required_capability=capability(),
        state=WorkUnitState.AWAITING_REVIEW,
        delivered_artifact_version=ImmutableVersionRef(kind="git_commit", value="review-v1"),
        previous_worker="worker-a",
    )
    rejected = WorkUnit(
        id="rejected",
        title="rejected",
        required_capability=capability(),
        state=WorkUnitState.REJECTED,
        delivered_artifact_version=ImmutableVersionRef(kind="git_commit", value="rejected-v1"),
        previous_worker="worker-a",
    )
    for unit in (upstream, ready, review, rejected):
        add(sf, ORG, unit)

    snapshot = WorkQueueMetricsService(sf, organization_id=ORG).snapshot()

    assert snapshot.queue_depth == 3
    assert snapshot.ready_queue_depth == 1
    assert snapshot.review_queue_depth == 1


def test_ready_queue_requires_immutable_upstream_delivery_version() -> None:
    sf = factory()
    add(
        sf,
        ORG,
        WorkUnit(
            id="upstream",
            title="upstream",
            required_capability=capability(),
            state=WorkUnitState.APPROVED,
        ),
    )
    add(
        sf,
        ORG,
        WorkUnit(
            id="downstream",
            title="downstream",
            required_capability=capability(),
            depends_on=("upstream",),
        ),
    )

    snapshot = WorkQueueMetricsService(sf, organization_id=ORG).snapshot()

    assert snapshot.queue_depth == 1
    assert snapshot.ready_queue_depth == 0


def test_runtime_observations_compute_means_rates_and_utilization() -> None:
    sf = factory()
    metrics = WorkQueueMetrics()
    metrics.record_claim(latency_seconds=1.0, conflict=False)
    metrics.record_claim(latency_seconds=3.0, conflict=True)
    metrics.record_worker_busy(30)
    metrics.record_worker_idle(10)
    metrics.record_execution(8)
    metrics.record_execution(12)
    metrics.record_review_wait(5)
    metrics.record_review_wait(7)
    metrics.record_review(duration_seconds=4, rejected=False)
    metrics.record_review(duration_seconds=6, rejected=True)
    metrics.record_rework()
    metrics.record_lease_expiry()
    metrics.record_lease_expiry()

    snapshot = WorkQueueMetricsService(sf, organization_id=ORG, metrics=metrics).snapshot()

    assert snapshot.claim_latency == 2.0
    assert snapshot.claim_conflict_rate == 0.5
    assert snapshot.worker_busy_time == 30.0
    assert snapshot.worker_idle_time == 10.0
    assert snapshot.worker_utilization == 0.75
    assert snapshot.execution_duration == 10.0
    assert snapshot.review_wait_time == 6.0
    assert snapshot.review_duration == 5.0
    assert snapshot.rejection_rate == 0.5
    assert snapshot.rework_rate == 1.0
    assert snapshot.lease_expiry_count == 2


def test_metrics_are_tenant_scoped() -> None:
    sf = factory()
    add(
        sf,
        ORG,
        WorkUnit(id="org-unit", title="org-unit", required_capability=capability()),
    )
    add(
        sf,
        OTHER,
        WorkUnit(id="other-unit", title="other-unit", required_capability=capability()),
    )

    ours = WorkQueueMetricsService(sf, organization_id=ORG).snapshot()
    theirs = WorkQueueMetricsService(sf, organization_id=OTHER).snapshot()

    assert ours.queue_depth == 1
    assert theirs.queue_depth == 1


def test_snapshot_is_observational_and_does_not_append_revisions() -> None:
    sf = factory()
    add(
        sf,
        ORG,
        WorkUnit(id="wu", title="wu", required_capability=capability()),
    )
    before = history(sf, ORG, "wu")

    service = WorkQueueMetricsService(sf, organization_id=ORG)
    first = service.snapshot()
    second = service.snapshot()

    assert first == second
    after = history(sf, ORG, "wu")
    assert len(before) == len(after) == 1
    assert before[0].state is after[0].state is WorkUnitState.PENDING


def test_invalid_durations_fail_closed() -> None:
    metrics = WorkQueueMetrics()

    for invalid in (-1, float("inf"), float("nan"), True, "1"):
        try:
            metrics.record_execution(invalid)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid duration {invalid!r} was accepted")
