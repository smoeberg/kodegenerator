from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.capability import Capability, CapabilityLevel
from domain.work_queue import (
    DependencyVersionBinding,
    ImmutableVersionRef,
    WorkUnit,
    WorkUnitState,
    WorkerLease,
)
from infrastructure.persistence.models import Base
from infrastructure.persistence.work_queue_repository import (
    WorkUnitConflictError,
    WorkUnitPersistenceError,
    WorkUnitRepository,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as s:
        yield s


def test_work_unit_round_trip_persistence(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(
        id="capability.python",
        name="Python Developer",
        description="Expert Python",
        level=CapabilityLevel.EXPERT,
        certification="Certified",
        used_by=["bot-1"],
    )
    base_ver = ImmutableVersionRef(kind="git_commit", value="abc1234")
    delivered_ver = ImmutableVersionRef(kind="git_commit", value="def5678")
    snapshot = DependencyVersionBinding(
        work_unit_id="wu-upstream",
        version=ImmutableVersionRef(kind="git_commit", value="upstream1"),
    )
    lease = WorkerLease(
        lease_id="lease-1",
        worker_id="worker-1",
        claimed_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    wu = WorkUnit(
        id="wu-101",
        title="Test Work Unit",
        required_capability=cap,
        state=WorkUnitState.CLAIMED,
        depends_on=("wu-upstream",),
        depends_on_snapshot=(snapshot,),
        base_version=base_ver,
        allowed_resources=("resource-1",),
        acceptance_refs=("ref-1",),
        delivered_artifact_version=delivered_ver,
        claimed_by="worker-1",
        lease=lease,
        previous_worker="worker-0",
        rework_attempts=1,
    )

    repo.add("org-1", wu)
    session.commit()

    loaded = repo.get("org-1", "wu-101")
    assert loaded is not None
    assert loaded.id == wu.id
    assert loaded.title == wu.title
    assert loaded.state == wu.state
    assert loaded.required_capability.id == cap.id
    assert loaded.required_capability.name == cap.name
    assert loaded.required_capability.level == cap.level
    assert loaded.depends_on == wu.depends_on
    assert len(loaded.depends_on_snapshot) == 1
    assert loaded.depends_on_snapshot[0].work_unit_id == "wu-upstream"
    assert loaded.depends_on_snapshot[0].version.value == "upstream1"
    assert loaded.base_version.value == "abc1234"
    assert loaded.allowed_resources == wu.allowed_resources
    assert loaded.acceptance_refs == wu.acceptance_refs
    assert loaded.delivered_artifact_version.value == "def5678"
    assert loaded.claimed_by == "worker-1"
    assert loaded.lease.lease_id == "lease-1"
    assert loaded.previous_worker == "worker-0"
    assert loaded.rework_attempts == 1


def test_tenant_isolation(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.test", name="Test Cap")
    wu = WorkUnit(id="wu-shared", title="Shared ID", required_capability=cap)

    repo.add("org-1", wu)
    session.commit()

    assert repo.get("org-1", "wu-shared") is not None
    assert repo.get("org-2", "wu-shared") is None
    assert len(repo.list_for_organization("org-1")) == 1
    assert len(repo.list_for_organization("org-2")) == 0


def test_conflict_and_missing_update(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.test", name="Test Cap")
    wu = WorkUnit(id="wu-1", title="First", required_capability=cap)

    repo.add("org-1", wu)
    with pytest.raises(WorkUnitConflictError):
        repo.add("org-1", wu)

    missing = WorkUnit(id="wu-nonexistent", title="Missing", required_capability=cap)
    with pytest.raises(WorkUnitPersistenceError):
        repo.update("org-1", missing)


def test_capability_corruption_fail_closed(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.test", name="Test Cap", level=CapabilityLevel.BEGINNER)
    wu = WorkUnit(id="wu-corrupt", title="Corrupt", required_capability=cap)
    repo.add("org-1", wu)
    session.commit()

    # Manually corrupt capability in database table
    from infrastructure.persistence.work_queue_models import WorkUnitModel
    model = session.get(WorkUnitModel, ("org-1", "wu-corrupt"))

    # Case 1: invalid level name
    model.required_capability = {"id": "cap.test", "name": "Test Cap", "level": "INVALID_LEVEL"}
    session.flush()
    with pytest.raises(WorkUnitPersistenceError):
        repo.get("org-1", "wu-corrupt")

    # Case 2: missing id
    model.required_capability = {"name": "Test Cap", "level": "BEGINNER"}
    session.flush()
    with pytest.raises(WorkUnitPersistenceError):
        repo.get("org-1", "wu-corrupt")

    # Case 3: missing name
    model.required_capability = {"id": "cap.test", "level": "BEGINNER"}
    session.flush()
    with pytest.raises(WorkUnitPersistenceError):
        repo.get("org-1", "wu-corrupt")


def test_provenance_history_and_revisions(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.prov", name="Prov Cap")

    # Revision 1: initial add with artifact v1
    v1 = ImmutableVersionRef(kind="git_commit", value="art-v1")
    wu = WorkUnit(id="wu-prov", title="Prov Test", required_capability=cap, delivered_artifact_version=v1)
    repo.add("org-1", wu)
    session.commit()

    history = repo.list_history("org-1", "wu-prov")
    assert len(history) == 1
    assert history[0].delivered_artifact_version.value == "art-v1"

    # Revision 2: update with artifact v2
    v2 = ImmutableVersionRef(kind="git_commit", value="art-v2")
    wu_v2 = WorkUnit(
        id="wu-prov",
        title="Prov Test Updated",
        required_capability=cap,
        state=WorkUnitState.APPROVED,
        delivered_artifact_version=v2,
    )
    repo.update("org-1", wu_v2)
    session.commit()

    history = repo.list_history("org-1", "wu-prov")
    assert len(history) == 2
    assert history[0].delivered_artifact_version.value == "art-v1"
    assert history[0].state == WorkUnitState.PENDING
    assert history[1].delivered_artifact_version.value == "art-v2"
    assert history[1].state == WorkUnitState.APPROVED
    assert history[1].title == "Prov Test Updated"


def test_dependency_snapshot_history(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.snap", name="Snap Cap")

    snap1 = DependencyVersionBinding(
        work_unit_id="up-1", version=ImmutableVersionRef(kind="git_commit", value="snap-v1")
    )
    wu = WorkUnit(id="wu-snap", title="Snap Test", required_capability=cap, depends_on_snapshot=(snap1,))
    repo.add("org-1", wu)
    session.commit()

    snap2 = DependencyVersionBinding(
        work_unit_id="up-1", version=ImmutableVersionRef(kind="git_commit", value="snap-v2")
    )
    wu_v2 = WorkUnit(id="wu-snap", title="Snap Test 2", required_capability=cap, depends_on_snapshot=(snap2,))
    repo.update("org-1", wu_v2)
    session.commit()

    history = repo.list_history("org-1", "wu-snap")
    assert len(history) == 2
    assert history[0].depends_on_snapshot[0].version.value == "snap-v1"
    assert history[1].depends_on_snapshot[0].version.value == "snap-v2"


def test_metadata_canonical_registration() -> None:
    # Verify that importing persistence package registers work_units and work_unit_revisions
    # without needing to import WorkUnitRepository explicitly.
    from infrastructure.persistence import Base
    table_names = Base.metadata.tables.keys()
    assert "work_units" in table_names
    assert "work_unit_revisions" in table_names
