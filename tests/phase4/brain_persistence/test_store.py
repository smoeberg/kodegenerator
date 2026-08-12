from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.brain_persistence import KnowledgeConflictError, KnowledgeStore
from phase4.contracts import Evidence, KnowledgeRecord, KnowledgeState


def make_store() -> KnowledgeStore:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return KnowledgeStore(sessions)


def record(record_id: str, *, version: int = 0, state: KnowledgeState = KnowledgeState.PROPOSED) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id=record_id,
        subject="python",
        claim="Python is dynamically typed.",
        evidence=(Evidence("e-1", "language-spec", "digest-1"),),
        state=state,
        version=version,
        author_agent_id="agent-1",
    )


def test_first_record_materializes_version_one() -> None:
    store = make_store()

    assert store.append_and_materialize(record("r-1")) == 1

    state = store.get_state("python")
    assert state is not None
    assert state.version == 1
    assert state.state == "proposed"


def test_second_record_requires_current_version_and_advances_state() -> None:
    store = make_store()
    store.append_and_materialize(record("r-1"))

    assert store.append_and_materialize(record("r-2", version=1, state=KnowledgeState.CONFIRMED)) == 2
    state = store.get_state("python")
    assert state is not None
    assert state.version == 2
    assert state.state == "confirmed"


def test_stale_writer_is_rejected_without_materializing() -> None:
    store = make_store()
    store.append_and_materialize(record("r-1"))

    try:
        store.append_and_materialize(record("r-stale"))
    except KnowledgeConflictError:
        pass
    else:
        raise AssertionError("stale writer must be rejected")

    state = store.get_state("python")
    assert state is not None
    assert state.version == 1


def test_failed_transition_does_not_append_record() -> None:
    store = make_store()
    store.append_and_materialize(record("r-1"))

    try:
        store.append_and_materialize(record("r-stale", version=0))
    except KnowledgeConflictError:
        pass

    with store.session_factory() as session:
        from phase4.brain_persistence.models import KnowledgeRecordModel

        rows = session.query(KnowledgeRecordModel).all()
        assert [row.record_id for row in rows] == ["r-1"]
