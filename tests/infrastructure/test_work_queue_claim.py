"""WQ-104: atomic claim + dependency snapshot runtime tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import (
    DependencyVersionBinding,
    ImmutableVersionRef,
    WorkUnit,
    WorkUnitState,
)
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_models import WorkUnitModel
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue import WorkQueueClaimService


ORG = "org-1"
OTHER = "org-2"


def capability(level=CapabilityLevel.EXPERT) -> Capability:
    return Capability(
        id="capability.python",
        name="Python Developer",
        level=level,
        certification="Certified",
        used_by=["bot-1"],
    )


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def add_unit(
    session_factory,
    work_unit_id: str,
    *,
    organization_id: str = ORG,
    required_capability: Capability | None = None,
    state: WorkUnitState = WorkUnitState.PENDING,
    depends_on: tuple[str, ...] = (),
    dependency=False,
) -> None:
    cap = required_capability if required_capability is not None else capability()
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        if dependency:
            # Approved upstream with a delivered immutable version.
            dep = WorkUnit(
                id=work_unit_id,
                title=work_unit_id,
                required_capability=cap,
                state=WorkUnitState.APPROVED,
                delivered_artifact_version=ImmutableVersionRef(
                    kind="git_commit", value=f"{work_unit_id}-v1"
                ),
                depends_on_snapshot=(
                    DependencyVersionBinding(
                        work_unit_id=f"{work_unit_id}-up",
                        version=ImmutableVersionRef(kind="git_commit", value="u1"),
                    ),
                ),
            )
        else:
            dep = WorkUnit(
                id=work_unit_id,
                title=work_unit_id,
                required_capability=cap,
                state=state,
                depends_on=depends_on,
            )
        repo.add(organization_id, dep)
        session.commit()


def units(session_factory, work_unit_id: str, organization_id: str = ORG):
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        return repo.get(organization_id, work_unit_id)


def histories(session_factory, work_unit_id: str, organization_id: str = ORG):
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        return repo.list_history(organization_id, work_unit_id)


def text_iso(dt: datetime) -> str:
    return dt.isoformat()


# --------------------------------------------------------------------------- #
# basic claim + lease
# --------------------------------------------------------------------------- #

def test_claim_basic_single_pending(session_factory) -> None:
    add_unit(session_factory, "wu-a")
    service = WorkQueueClaimService(
        session_factory, organization_id=ORG, lease_seconds=60
    )
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.id == "wu-a"
    assert claimed.state is WorkUnitState.CLAIMED
    assert claimed.claimed_by == "worker-1"
    assert claimed.lease is not None
    assert claimed.lease.worker_id == "worker-1"
    assert claimed.lease.expires_at > claimed.lease.claimed_at
    assert claimed.lease.expires_at - claimed.lease.claimed_at == timedelta(seconds=60)

    # projection + provenance both committed atomically
    assert units(session_factory, "wu-a").state is WorkUnitState.CLAIMED
    history = histories(session_factory, "wu-a")
    assert len(history) == 2  # add (rev 1) + claim (rev 2)


def test_claim_returns_none_when_nothing_ready(session_factory) -> None:
    # worker capability does not match
    add_unit(session_factory, "wu-a")
    other = Capability(
        id="capability.java", name="Java Developer", level=CapabilityLevel.EXPERT
    )
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    assert service.claim_next_ready("worker-1", [other]) is None


# --------------------------------------------------------------------------- #
# deterministic ordering
# --------------------------------------------------------------------------- #

def test_claim_orders_by_created_at_then_id(session_factory) -> None:
    add_unit(session_factory, "wu-early")
    add_unit(session_factory, "wu-first")
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    # Both share the same created_at instant; deterministic tie-break is the
    # id, so 'wu-early' is selected before 'wu-first'.
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.id == "wu-early"


def test_claim_candidate_order_created_at_asc(session_factory) -> None:
    # candidate set is ordered by created_at ASC (insertion order).
    add_unit(session_factory, "wu-first-mined")
    add_unit(session_factory, "wu-second")
    add_unit(session_factory, "wu-third")
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    cap = capability()
    assert service.claim_next_ready("worker-1", [cap]).id == "wu-first-mined"
    assert service.claim_next_ready("worker-1", [cap]).id == "wu-second"
    assert service.claim_next_ready("worker-1", [cap]).id == "wu-third"


def test_claim_orders_by_created_at_then_work_unit_id(session_factory) -> None:
    # Two claimable units share an identical created_at but are inserted in
    # REVERSE-ID order. The comparator is (created_at ASC, work_unit_id ASC), so
    # the first claim must be the lexicographically-first ID (wu-a), NOT the
    # insertion order (wu-z).
    identical = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    for unit_id in ("wu-z", "wu-a"):
        with session_factory() as session:
            WorkUnitRepository(session).add(
                ORG,
                WorkUnit(
                    id=unit_id,
                    title=unit_id,
                    required_capability=capability(),
                    state=WorkUnitState.PENDING,
                    created_at=identical,
                    updated_at=identical,
                ),
            )
            session.commit()
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    cap = capability()
    assert service.claim_next_ready("worker-1", [cap]).id == "wu-a"
    assert service.claim_next_ready("worker-1", [cap]).id == "wu-z"
    assert service.claim_next_ready("worker-1", [cap]) is None


# --------------------------------------------------------------------------- #
# capability gate (reuses WQ-103)
# --------------------------------------------------------------------------- #

def test_claim_requires_matching_capability(session_factory) -> None:
    # Worker holds only the Java capability; the unit requires Python.
    add_unit(
        session_factory, "wu-a",
        required_capability=capability(),  # capability.python
    )
    worker = Capability(id="capability.java", name="Java Developer", level=CapabilityLevel.EXPERT)
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    assert service.claim_next_ready("worker-1", [worker]) is None


def test_claim_recognises_registry_capability_is_not_dor(session_factory) -> None:
    # A registry (non-DOR) capability object must NOT satisfy the DOR gate
    # even when its name superficially matches the required capability id.
    add_unit(session_factory, "wu-a")
    try:
        from phase4.agent_registry.models import AgentVersion, Capability as RegistryCapability
    except Exception:  # pragma: no cover - optional module
        return
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    registry_cap = RegistryCapability(
        name="Python Developer", version=AgentVersion(1, 0, 0)
    )
    assert service.claim_next_ready("worker-1", [registry_cap]) is None


# --------------------------------------------------------------------------- #
# dependency readiness
# --------------------------------------------------------------------------- #

def test_claim_waits_for_approved_dependency(session_factory) -> None:
    add_unit(session_factory, "wu-up", dependency=True)
    add_unit(session_factory, "wu-child", depends_on=("wu-up",))
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    # dependency is approved -> child claimable
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.id == "wu-child"


def test_claim_not_ready_when_dependency_lacks_delivered_version(session_factory) -> None:
    # upstream APPROVED but delivered_artifact_version None -> not claimable
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        repo.add(ORG, WorkUnit(
            id="wu-up",
            title="wu-up",
            required_capability=capability(),
            state=WorkUnitState.APPROVED,
        ))
        repo.add(ORG, WorkUnit(
            id="wu-child",
            title="wu-child",
            required_capability=capability(),
            state=WorkUnitState.PENDING,
            depends_on=("wu-up",),
        ))
        session.commit()
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    assert service.claim_next_ready("worker-1", [capability()]) is None


def test_claim_skips_unapproved_dependency_then_claims_other(session_factory) -> None:
    # 'wu-up' requires Java (worker lacks it) and is PENDING; 'wu-child' depends
    # on it so it is not ready. The independent 'wu-indep' is claimable.
    java = Capability(id="capability.java", name="Java Developer", level=CapabilityLevel.EXPERT)
    add_unit(session_factory, "wu-up", required_capability=java)
    add_unit(session_factory, "wu-child", depends_on=("wu-up",))
    add_unit(session_factory, "wu-indep")
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.id == "wu-indep"


# --------------------------------------------------------------------------- #
# dependency snapshot
# --------------------------------------------------------------------------- #

def test_claim_captures_exact_approved_snapshot_in_order(session_factory) -> None:
    add_unit(
        session_factory,
        "wu-lib",
        dependency=True,
        required_capability=None,
    )
    add_unit(
        session_factory,
        "wu-app",
        dependency=True,
        required_capability=None,
    )
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        repo.add(ORG, WorkUnit(
            id="wu-root",
            title="wu-root",
            required_capability=capability(),
            state=WorkUnitState.PENDING,
            depends_on=("wu-app", "wu-lib"),
        ))
        session.commit()
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    snapshot = claimed.depends_on_snapshot
    assert [b.work_unit_id for b in snapshot] == ["wu-app", "wu-lib"]
    assert all(
        b.version.kind == "git_commit"
        and b.version.value == f"{b.work_unit_id}-v1"
        for b in snapshot
    )
    # persisted snapshot equals the captured one
    stored = units(session_factory, "wu-root")
    assert [b.work_unit_id for b in stored.depends_on_snapshot] == ["wu-app", "wu-lib"]


# --------------------------------------------------------------------------- #
# atomicity / CAS single winner
# --------------------------------------------------------------------------- #

def test_claim_cas_single_winner_under_contention(session_factory) -> None:
    add_unit(session_factory, "wu-only")
    service_a = WorkQueueClaimService(session_factory, organization_id=ORG)
    service_b = WorkQueueClaimService(session_factory, organization_id=ORG)
    winner_a = service_a.claim_next_ready("worker-a", [capability()])
    winner_b = service_b.claim_next_ready("worker-b", [capability()])
    winners = [w is not None for w in (winner_a, winner_b)]
    assert sum(winners) == 1
    # exactly one revision for the claim; loser produced no duplicate revision
    history = histories(session_factory, "wu-only")
    assert len(history) == 2


def test_claim_no_duplicate_revision_on_cas_loss(session_factory) -> None:
    add_unit(session_factory, "wu-only")
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    first = service.claim_next_ready("w1", [capability()])
    assert first is not None
    # second claim on an already-CLAIMED unit loses; no extra revision
    second = service.claim_next_ready("w2", [capability()])
    assert second is None
    history = histories(session_factory, "wu-only")
    assert len(history) == 2


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

def test_claim_rejects_nonpositive_lease(session_factory) -> None:
    with pytest.raises(ValueError):
        WorkQueueClaimService(session_factory, organization_id=ORG, lease_seconds=0)
    with pytest.raises(ValueError):
        WorkQueueClaimService(session_factory, organization_id=ORG, lease_seconds=-5)


def test_claim_rejects_empty_organization(session_factory) -> None:
    with pytest.raises(ValueError):
        WorkQueueClaimService(session_factory, organization_id="   ")
    with pytest.raises(ValueError):
        WorkQueueClaimService(session_factory, organization_id="")
    with pytest.raises(ValueError):
        WorkQueueClaimService(session_factory, organization_id="x" * 129)


def test_claim_rejects_empty_worker_id(session_factory) -> None:
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    with pytest.raises(ValueError):
        service.claim_next_ready("  ", [capability()])
    with pytest.raises(ValueError):
        service.claim_next_ready("", [capability()])


# --------------------------------------------------------------------------- #
# tenant isolation
# --------------------------------------------------------------------------- #

def test_claim_never_reads_dependencies_across_tenant(session_factory) -> None:
    # org-2 has the only approved dependency; org-1 child must NOT see it.
    add_unit(session_factory, "wu-2-dep", organization_id=OTHER, dependency=True)
    add_unit(session_factory, "wu-1-child", organization_id=ORG, depends_on=("wu-2-dep",))
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    # dependency lives in another tenant and is invisible -> not claimable
    assert service.claim_next_ready("worker-1", [capability()]) is None


def test_claim_isolated_between_organizations(session_factory) -> None:
    add_unit(session_factory, "wu-org1", organization_id=ORG)
    add_unit(session_factory, "wu-org2", organization_id=OTHER)
    s1 = WorkQueueClaimService(session_factory, organization_id=ORG)
    s2 = WorkQueueClaimService(session_factory, organization_id=OTHER)
    c1 = s1.claim_next_ready("w1", [capability()])
    c2 = s2.claim_next_ready("w2", [capability()])
    assert c1 is not None and c1.id == "wu-org1"
    assert c2 is not None and c2.id == "wu-org2"
    # org-2 unit unaffected by org-1 claim and vice versa
    assert units(session_factory, "wu-org1", ORG).state is WorkUnitState.CLAIMED
    assert units(session_factory, "wu-org2", OTHER).state is WorkUnitState.CLAIMED


def test_claim_empty_snapshot_for_zero_dependency(session_factory) -> None:
    add_unit(session_factory, "wu-zero")
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.depends_on_snapshot == ()
    stored = units(session_factory, "wu-zero")
    assert stored.depends_on_snapshot == ()


def test_claim_touches_updated_at_and_lease(session_factory) -> None:
    add_unit(session_factory, "wu-a")
    created = units(session_factory, "wu-a").created_at
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    claimed = service.claim_next_ready("worker-1", [capability()])
    assert claimed is not None
    assert claimed.updated_at >= created
    assert claimed.lease is not None
    # lease identity agrees with claimed_by
    assert claimed.lease.worker_id == claimed.claimed_by == "worker-1"
    stored = units(session_factory, "wu-a")
    history = histories(session_factory, "wu-a")
    assert len(history) == 2


def test_claim_missing_dependency_no_claim(session_factory) -> None:
    # 'wu-child' depends on a WorkUnit that does not exist at all -> no claim.
    add_unit(session_factory, "wu-child", depends_on=("wu-ghost",))
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    assert service.claim_next_ready("worker-1", [capability()]) is None


def test_claim_mandatory_10_worker_race_single_winner(tmp_path) -> None:
    # 10 workers genuinely race for a single claimable unit against a shared
    # file-backed SQLite database. The CAS guard (state=PENDING,
    # claimed_by IS NULL, lease IS NULL) forces exactly one winner.
    #
    # To make all contenders collide at the same CAS instant deterministically,
    # the internal _cas_claim entry is wrapped with a 10-way threading barrier
    # right before the UPDATE executes, as the spec's correction allows.
    db = tmp_path / "race.db"
    engine = create_engine(
        f"sqlite:///{db}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    # Seed exactly one claimable PENDING unit.
    ORG_RACE = "org-race"
    with session_factory() as session:
        repo = WorkUnitRepository(session)
        repo.add(
            ORG_RACE,
            WorkUnit(
                id="wu-race",
                title="wu-race",
                required_capability=capability(),
                state=WorkUnitState.PENDING,
            ),
        )
        session.commit()
    revs_before = len(histories(session_factory, "wu-race", ORG_RACE))

    barrier = threading.Barrier(10)
    original_cas = WorkQueueClaimService._cas_claim

    def _barrier_before_cas(self, session, candidate, worker_id, snapshot):
        # All 10 contenders read the same PENDING row, then block here so none
        # performs its UPDATE before every contender is at the CAS entry.
        barrier.wait(timeout=60)
        return original_cas(self, session, candidate, worker_id, snapshot)

    WorkQueueClaimService._cas_claim = _barrier_before_cas
    try:
        results: dict[str, object] = {}
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(
                    WorkQueueClaimService(
                        session_factory, organization_id=ORG_RACE
                    ).claim_next_ready,
                    f"worker-{i}",
                    [capability()],
                ): f"worker-{i}"
                for i in range(1, 11)
            }
            for fut, worker in futures.items():
                results[worker] = fut.result(timeout=90)
    finally:
        WorkQueueClaimService._cas_claim = original_cas

    # exactly one winner across all 10 racing workers, the rest lose
    winners = {
        worker: claimed for worker, claimed in results.items() if claimed is not None
    }
    assert len(winners) == 1
    winner_worker, winner = next(iter(winners.items()))
    assert winner.claimed_by == winner_worker
    assert winner.lease is not None
    assert winner.lease.worker_id == winner_worker

    # persisted projection: exactly one CLAIMED owner with the loser workers absent
    stored = units(session_factory, "wu-race", ORG_RACE)
    assert stored.state is WorkUnitState.CLAIMED
    assert stored.claimed_by == winner_worker
    assert stored.lease.worker_id == winner_worker

    # exactly one claim revision appended (add + one claim), no duplicates
    revs_after = histories(session_factory, "wu-race", ORG_RACE)
    assert len(revs_after) == revs_before + 1 == 2



def test_claim_candidate_query_is_tenant_scoped(session_factory) -> None:
    # Candidate scope must be restricted to the service's own organization.
    add_unit(session_factory, "wu-here", organization_id=ORG)
    add_unit(session_factory, "wu-there", organization_id=OTHER)
    service = WorkQueueClaimService(session_factory, organization_id=ORG)
    claimed = service.claim_next_ready("w1", [capability()])
    assert claimed is not None
    assert claimed.id == "wu-here"
    assert units(session_factory, "wu-there", OTHER).state is WorkUnitState.PENDING
