"""SC-101C acceptance coverage for project-scoped Work Queue supersession."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import (
    ImmutableVersionRef,
    WorkerLease,
    WorkUnit,
    WorkUnitContractError,
    WorkUnitState,
)
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_scope import (
    ProjectScopedWorkQueueClaimService,
    ProjectScopedWorkQueueLeaseService,
    bind_work_unit_scope,
    request_superseded_scope_cancellation,
    work_unit_scope,
)

ORG = "org-1"
PROJECT = "project-1"
P1 = "1" * 64
P2 = "2" * 64


def capability() -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=CapabilityLevel.EXPERT,
    )


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


class Database:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    @contextmanager
    def session(self, organization_id: str):
        assert organization_id == ORG
        with self.session_factory() as session:
            yield session


def add_scoped(session_factory, work_unit_id: str, plan: str) -> None:
    work_unit = bind_work_unit_scope(
        WorkUnit(
            id=work_unit_id,
            title=work_unit_id,
            required_capability=capability(),
        ),
        project_id=PROJECT,
        plan_request_fingerprint=plan,
    )
    with session_factory() as session:
        WorkUnitRepository(session).add(ORG, work_unit)
        session.commit()


def get_unit(session_factory, work_unit_id: str) -> WorkUnit:
    with session_factory() as session:
        work_unit = WorkUnitRepository(session).get(ORG, work_unit_id)
    assert work_unit is not None
    return work_unit


def test_scope_binding_is_immutable_and_idempotent() -> None:
    original = WorkUnit(
        id="wu-1",
        title="wu-1",
        required_capability=capability(),
    )
    bound = bind_work_unit_scope(
        original,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
    )
    assert work_unit_scope(bound) == (PROJECT, P1)
    assert (
        bind_work_unit_scope(
            bound,
            project_id=PROJECT,
            plan_request_fingerprint=P1,
        )
        is bound
    )
    with pytest.raises(WorkUnitContractError, match="immutable"):
        bind_work_unit_scope(
            bound,
            project_id=PROJECT,
            plan_request_fingerprint=P2,
        )


def test_p1_cannot_receive_new_claim_after_p2_becomes_active(session_factory) -> None:
    active = {"plan": P1}

    def validator(organization_id: str, project_id: str, plan: str) -> bool:
        return (
            organization_id == ORG and project_id == PROJECT and plan == active["plan"]
        )

    add_scoped(session_factory, "p1-first", P1)
    add_scoped(session_factory, "p1-late", P1)
    add_scoped(session_factory, "p2-next", P2)

    p1 = ProjectScopedWorkQueueClaimService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=validator,
    )
    first = p1.claim_next_ready("worker-p1", [capability()])
    assert first is not None and first.id == "p1-first"

    active["plan"] = P2

    # P1 has another ready unit, but it is now stale and must not be claimed.
    assert p1.claim_next_ready("worker-stale", [capability()]) is None

    p2 = ProjectScopedWorkQueueClaimService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P2,
        scope_validator=validator,
    )
    claimed_p2 = p2.claim_next_ready("worker-p2", [capability()])
    assert claimed_p2 is not None and claimed_p2.id == "p2-next"
    assert get_unit(session_factory, "p1-late").state is WorkUnitState.PENDING


def test_exact_scoped_claim_leaves_unrequested_eligible_unit_pending(
    session_factory,
) -> None:
    def validator(organization_id: str, project_id: str, plan: str) -> bool:
        return (organization_id, project_id, plan) == (ORG, PROJECT, P1)

    add_scoped(session_factory, "p1-earlier", P1)
    add_scoped(session_factory, "p1-requested", P1)
    service = ProjectScopedWorkQueueClaimService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=validator,
    )

    claimed = service.claim_ready("p1-requested", "worker-p1", [capability()])

    assert claimed is not None and claimed.id == "p1-requested"
    assert get_unit(session_factory, "p1-earlier").state is WorkUnitState.PENDING


def test_inflight_p1_is_cooperatively_fenced_when_p2_supersedes(
    session_factory,
) -> None:
    active = {"plan": P1}

    def validator(organization_id: str, project_id: str, plan: str) -> bool:
        return (
            organization_id == ORG and project_id == PROJECT and plan == active["plan"]
        )

    add_scoped(session_factory, "p1-inflight", P1)
    claim_service = ProjectScopedWorkQueueClaimService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=validator,
    )
    claimed = claim_service.claim_next_ready("worker-p1", [capability()])
    assert claimed is not None and claimed.lease is not None
    lease_id = claimed.lease.lease_id

    active["plan"] = P2

    lease_service = ProjectScopedWorkQueueLeaseService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=validator,
    )
    # Even before the cancellation attempt completes, the stale scope cannot
    # renew ownership or submit output through the lease boundary.
    assert (
        lease_service.heartbeat(
            "p1-inflight",
            worker_id="worker-p1",
            lease_id=lease_id,
        )
        is None
    )
    assert (
        lease_service.submit_for_review(
            "p1-inflight",
            worker_id="worker-p1",
            lease_id=lease_id,
            delivered_artifact_version=ImmutableVersionRef(
                kind="git_commit",
                value="stale-p1-output",
            ),
        )
        is None
    )

    changed = request_superseded_scope_cancellation(
        Database(session_factory),
        organization_id=ORG,
        project_id=PROJECT,
        active_plan_request_fingerprint=P2,
    )
    assert changed == 1

    stored = get_unit(session_factory, "p1-inflight")
    assert stored.state is WorkUnitState.FAILED
    assert stored.claimed_by is None
    assert stored.lease is None
    assert stored.previous_worker == "worker-p1"


def test_scoped_recovery_never_steals_expired_work_from_other_plan(
    session_factory,
) -> None:
    now = datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc)

    def validator(organization_id: str, project_id: str, plan: str) -> bool:
        return organization_id == ORG and project_id == PROJECT and plan == P1

    def expired(work_unit_id: str, plan: str, offset: int) -> WorkUnit:
        claimed_at = now - timedelta(minutes=2)
        unit = WorkUnit(
            id=work_unit_id,
            title=work_unit_id,
            required_capability=capability(),
            state=WorkUnitState.CLAIMED,
            claimed_by=f"old-{work_unit_id}",
            lease=WorkerLease(
                lease_id=f"lease-{work_unit_id}",
                worker_id=f"old-{work_unit_id}",
                claimed_at=claimed_at,
                expires_at=now - timedelta(minutes=1),
            ),
            created_at=now - timedelta(minutes=3),
            updated_at=now - timedelta(seconds=offset),
        )
        return bind_work_unit_scope(
            unit,
            project_id=PROJECT,
            plan_request_fingerprint=plan,
        )

    # The stale P2 row sorts first. A tenant-global recovery implementation
    # would incorrectly mutate it before noticing the scope mismatch.
    with session_factory() as session:
        repository = WorkUnitRepository(session)
        repository.add(ORG, expired("p2-expired", P2, 20))
        repository.add(ORG, expired("p1-expired", P1, 10))
        session.commit()

    service = ProjectScopedWorkQueueLeaseService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=validator,
        clock=lambda: now,
    )
    recovered = service.recover_next_expired("worker-new", [capability()])
    assert recovered is not None and recovered.id == "p1-expired"
    assert recovered.claimed_by == "worker-new"

    untouched = get_unit(session_factory, "p2-expired")
    assert untouched.claimed_by == "old-p2-expired"
    assert untouched.lease is not None
    assert untouched.lease.lease_id == "lease-p2-expired"


def test_scope_validator_failure_is_fail_closed(session_factory) -> None:
    add_scoped(session_factory, "p1", P1)

    def broken_validator(*_args):
        raise RuntimeError("scope authority unavailable")

    service = ProjectScopedWorkQueueClaimService(
        session_factory,
        organization_id=ORG,
        project_id=PROJECT,
        plan_request_fingerprint=P1,
        scope_validator=broken_validator,
    )
    assert service.claim_next_ready("worker-1", [capability()]) is None
    assert get_unit(session_factory, "p1").state is WorkUnitState.PENDING
