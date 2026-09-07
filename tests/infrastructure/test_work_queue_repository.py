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

    # Case 4: missing level (fail-closed, must not default to BEGINNER)
    model.required_capability = {"id": "cap.test", "name": "Test Cap"}
    session.flush()
    with pytest.raises(WorkUnitPersistenceError):
        repo.get("org-1", "wu-corrupt")

    # Case 5: malformed payload type (not a dict, e.g. string)
    model.required_capability = "corrupt-string-payload"
    session.flush()
    with pytest.raises(WorkUnitPersistenceError):
        repo.get("org-1", "wu-corrupt")


def test_ordinary_update_history(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.ord", name="Ordinary Cap")

    # Revision 1: initial add, state PENDING, previous_worker None
    wu = WorkUnit(id="wu-ord", title="Ordinary Test", required_capability=cap, state=WorkUnitState.PENDING)
    repo.add("org-1", wu)
    session.commit()

    # Revision 2: ordinary update changing state and previous_worker (no artifact change)
    wu_v2 = WorkUnit(
        id="wu-ord",
        title="Ordinary Test",
        required_capability=cap,
        state=WorkUnitState.CLAIMED,
        previous_worker="worker-alpha",
    )
    repo.update("org-1", wu_v2)
    session.commit()

    history = repo.list_history("org-1", "wu-ord")
    assert len(history) == 2
    assert history[0].state == WorkUnitState.PENDING
    assert history[0].previous_worker is None
    assert history[1].state == WorkUnitState.CLAIMED
    assert history[1].previous_worker == "worker-alpha"


def test_tenant_history_isolation(session) -> None:
    repo = WorkUnitRepository(session)
    cap = Capability(id="cap.tenant", name="Tenant Cap")

    # Same WorkUnit ID in two different organizations with different history updates
    wu_a = WorkUnit(id="wu-shared-id", title="Org A WU", required_capability=cap, state=WorkUnitState.PENDING)
    repo.add("org-A", wu_a)

    wu_b = WorkUnit(id="wu-shared-id", title="Org B WU", required_capability=cap, state=WorkUnitState.PENDING)
    repo.add("org-B", wu_b)
    session.commit()

    # Update org-A
    wu_a_v2 = WorkUnit(id="wu-shared-id", title="Org A WU Updated", required_capability=cap, state=WorkUnitState.APPROVED)
    repo.update("org-A", wu_a_v2)
    session.commit()

    history_a = repo.list_history("org-A", "wu-shared-id")
    history_b = repo.list_history("org-B", "wu-shared-id")

    assert len(history_a) == 2
    assert history_a[0].title == "Org A WU"
    assert history_a[1].title == "Org A WU Updated"
    assert history_a[1].state == WorkUnitState.APPROVED

    assert len(history_b) == 1
    assert history_b[0].title == "Org B WU"
    assert history_b[0].state == WorkUnitState.PENDING


def test_isolated_metadata_registration() -> None:
    import subprocess
    import sys
    from pathlib import Path

    # Resolve repository root portably from this test file's own location.
    repo_root = Path(__file__).resolve().parents[2]

    code = (
        "import infrastructure.persistence as p\n"
        "tables = list(p.Base.metadata.tables.keys())\n"
        "assert 'work_units' in tables, f'work_units missing: {tables}'\n"
        "assert 'work_unit_revisions' in tables, f'work_unit_revisions missing: {tables}'\n"
        "print('SUCCESS')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=repo_root
    )
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
    assert "SUCCESS" in result.stdout


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
