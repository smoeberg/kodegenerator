"""Durability, organization isolation, and OCC tests for Council runtime."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.council import (
    CouncilConflictError,
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    CouncilStore,
    DeliberationSession,
    DisputeStatus,
    SessionState,
)
from phase4.council.persistence_models import CouncilSessionModel  # noqa: F401
from phase4.epistemics import Evidence, EvidenceType, Hypothesis


@pytest.fixture
def council_store():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return CouncilStore(sessions)


def _session(*, max_rounds: int = 3) -> DeliberationSession:
    return DeliberationSession(
        Hypothesis(
            hypothesis_id="hyp-1",
            task_id="task-1",
            statement="Use durable Council state",
        ),
        max_rounds=max_rounds,
        approval_threshold=0.75,
        session_id="session-1",
    )


def _binding() -> CouncilSessionBinding:
    return CouncilSessionBinding(
        organization_id="org-1",
        context_packet_id="context-1",
        hypothesis_revision="hyp-rev-1",
        workspace_revision="git-rev-1",
    )


def test_round_trip_preserves_disputes_votes_evidence_and_org_scope(council_store):
    session = _session()
    dispute = session.raise_dispute("security", "Missing concurrency evidence")
    evidence = Evidence(
        evidence_id="evidence-1",
        hypothesis_id=session.hypothesis.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        source="ci",
        description="Concurrent writers rejected by state version",
    )
    session.resolve_dispute(dispute.dispute_id, evidence, "Verified by OCC test")
    session.cast_vote("security", True, "OCC proof is sufficient")

    persisted = council_store.create(session, _binding())
    loaded = council_store.get("org-1", session.session_id)

    assert persisted.state_version == 0
    assert loaded is not None
    assert loaded.binding == _binding()
    assert loaded.session.votes[1][0].agent_id == "security"
    restored_dispute = loaded.session.dispute_protocol.get_dispute(dispute.dispute_id)
    assert restored_dispute.status is DisputeStatus.RESOLVED
    assert restored_dispute.resolving_evidence.evidence_id == "evidence-1"
    assert council_store.evidence_revision_map("org-1", session.session_id) == {
        "evidence-1": "git-rev-1"
    }
    assert council_store.get("other-org", session.session_id) is None


def test_save_rejects_stale_writer(council_store):
    council_store.create(_session(), _binding())
    first = council_store.get("org-1", "session-1")
    stale = council_store.get("org-1", "session-1")
    assert first is not None and stale is not None

    first.session.cast_vote("architect", False)
    assert (
        council_store.save("org-1", first.session, expected_version=first.state_version)
        == 1
    )

    stale.session.cast_vote("security", False)
    with pytest.raises(CouncilConflictError, match="stale council state version"):
        council_store.save("org-1", stale.session, expected_version=stale.state_version)


def test_evidence_revision_binding_is_immutable(council_store):
    session = _session()
    evidence = Evidence(
        evidence_id="evidence-1",
        hypothesis_id=session.hypothesis.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        source="test",
        description="Original evidence",
    )
    session.hypothesis.supporting_evidence.append(evidence)
    council_store.create(session, _binding())
    loaded = council_store.get("org-1", "session-1")
    assert loaded is not None
    loaded.session.hypothesis.supporting_evidence[0].description = "Mutated"

    with pytest.raises(CouncilConflictError, match="immutable evidence binding"):
        council_store.save(
            "org-1", loaded.session, expected_version=loaded.state_version
        )


def test_persisted_votes_and_hypothesis_identity_are_immutable(council_store):
    session = _session()
    session.cast_vote("architect", True)
    council_store.create(session, _binding())
    loaded = council_store.get("org-1", "session-1")
    assert loaded is not None
    loaded.session.votes[1][0].approved = False

    with pytest.raises(CouncilConflictError, match="vote cannot be changed"):
        council_store.save(
            "org-1", loaded.session, expected_version=loaded.state_version
        )

    loaded = council_store.get("org-1", "session-1")
    assert loaded is not None
    loaded.session.hypothesis.statement = "Silently replace the hypothesis"
    with pytest.raises(CouncilConflictError, match="hypothesis binding"):
        council_store.save(
            "org-1", loaded.session, expected_version=loaded.state_version
        )


def test_deadlock_emits_human_required_once(council_store):
    council_store.create(_session(max_rounds=1), _binding())
    loaded = council_store.get("org-1", "session-1")
    assert loaded is not None
    loaded.session.cast_vote("security", False)
    assert loaded.session.conclude_round() is SessionState.DEADLOCKED
    council_store.save("org-1", loaded.session, expected_version=loaded.state_version)

    events = council_store.pending_events("org-1")
    assert [event.event_type for event in events] == [
        CouncilRuntimeEventType.SESSION_CREATED,
        CouncilRuntimeEventType.HUMAN_REQUIRED,
    ]
