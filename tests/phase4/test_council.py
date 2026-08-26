"""Unit tests for Phase 4 Council module."""

import pytest

from phase4.council import (
    DeliberationError,
    DeliberationSession,
    DisputeProtocol,
    DisputeProtocolError,
    DisputeStatus,
    SessionState,
)
from phase4.epistemics import Evidence, EvidenceType, Hypothesis, HypothesisStatus


@pytest.fixture
def sample_hypothesis():
    return Hypothesis(
        task_id="task-200",
        statement="Migrating from sync SQLite to async PostgreSQL will eliminate latency spikes",
        confidence=0.6,
        status=HypothesisStatus.ACTIVE,
    )


def test_council_session_initialization(sample_hypothesis):
    """Test initial session setup and initial OPEN state."""
    session = DeliberationSession(sample_hypothesis, max_rounds=4)

    assert session.state == SessionState.OPEN
    assert session.current_round == 1
    assert session.max_rounds == 4
    assert session.hypothesis.hypothesis_id == sample_hypothesis.hypothesis_id


def test_council_voting_and_decision_ready(sample_hypothesis):
    """Test smooth consensus path reaching DECISION_READY in round 1."""
    session = DeliberationSession(sample_hypothesis, max_rounds=4, approval_threshold=0.6)

    session.cast_vote(agent_id="agent-1", approved=True, rationale="Benchmarks demonstrate 4x throughput")
    session.cast_vote(agent_id="agent-2", approved=True, rationale="Pool contention removed")
    session.cast_vote(agent_id="agent-3", approved=False, rationale="Higher RAM footprint")

    final_state = session.conclude_round()
    assert final_state == SessionState.DECISION_READY
    assert session.state == SessionState.DECISION_READY


def test_council_dispute_requires_evidence_to_resolve(sample_hypothesis):
    """Test dispute lifecycle: creation transitions state to IN_DISPUTE and requires verified evidence."""
    session = DeliberationSession(sample_hypothesis, max_rounds=4)

    # 1. Raise dispute
    dispute = session.raise_dispute(
        agent_id="skeptic-agent",
        reason="PostgreSQL connection pooling overhead could exceed SQLite in single-process mode",
    )
    assert session.state == SessionState.IN_DISPUTE
    assert dispute.status == DisputeStatus.OPEN

    # 2. Voting blocked while in dispute
    with pytest.raises(DeliberationError, match="Cannot vote while active disputes"):
        session.cast_vote(agent_id="agent-1", approved=True)

    # 3. Cannot resolve with empty note or mismatched hypothesis
    bad_evidence = Evidence(
        hypothesis_id="wrong-hyp-id",
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.3,
        source="load_test",
        description="Async PG load test",
    )
    with pytest.raises(DisputeProtocolError):
        session.resolve_dispute(dispute.dispute_id, bad_evidence, resolution_note="valid note")

    # 4. Resolve properly with verified evidence
    good_evidence = Evidence(
        hypothesis_id=sample_hypothesis.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.3,
        source="load_test_suite",
        description="Async pool connection multiplexing benchmarked at 25,000 req/s with low CPU",
    )
    resolved_dispute = session.resolve_dispute(
        dispute.dispute_id,
        good_evidence,
        resolution_note="Verified with empirical load test benchmark suite",
    )

    assert resolved_dispute.status == DisputeStatus.RESOLVED
    assert session.state == SessionState.OPEN
    # Hypothesis confidence was updated by epistemic engine
    assert session.hypothesis.confidence == 0.9


def test_council_max_rounds_triggers_deadlock(sample_hypothesis):
    """Test that failing to achieve consensus within max_rounds marks session as DEADLOCKED."""
    max_rounds = 3
    session = DeliberationSession(sample_hypothesis, max_rounds=max_rounds, approval_threshold=0.8)

    for r in range(1, max_rounds):
        session.cast_vote("agent-1", approved=True)
        session.cast_vote("agent-2", approved=False)
        state = session.conclude_round()
        assert state == SessionState.OPEN
        assert session.current_round == r + 1

    # Last round (round 3)
    session.cast_vote("agent-1", approved=True)
    session.cast_vote("agent-2", approved=False)
    final_state = session.conclude_round()

    assert final_state == SessionState.DEADLOCKED
    assert session.state == SessionState.DEADLOCKED
    assert session.current_round == 3

    # Subsequent votes or conclusion blocked
    with pytest.raises(DeliberationError, match="Cannot vote in terminal state"):
        session.cast_vote("agent-3", approved=True)


def test_council_dispute_dismissal():
    """Test formal dismissal of invalid dispute."""
    hyp = Hypothesis(task_id="task-300", statement="Index improves query time", confidence=0.7)
    protocol = DisputeProtocol()

    dispute = protocol.raise_dispute(hyp, "agent-doubter", "Vague objection without substance")
    assert dispute.status == DisputeStatus.OPEN

    # Short justification rejected
    with pytest.raises(DisputeProtocolError, match="substantial justification"):
        protocol.dismiss_dispute(dispute.dispute_id, justification="No")

    # Proper dismissal
    dismissed = protocol.dismiss_dispute(
        dispute.dispute_id,
        justification="Objection lacks empirical basis and query plan confirms index scan usage.",
    )
    assert dismissed.status == DisputeStatus.DISMISSED
    assert not protocol.has_active_disputes(hyp.hypothesis_id)


def test_prevent_duplicate_votes_in_same_round(sample_hypothesis):
    """Test that an agent cannot vote more than once in the same round."""
    session = DeliberationSession(sample_hypothesis)
    session.cast_vote("agent-1", approved=True)

    with pytest.raises(DeliberationError, match="already voted in round"):
        session.cast_vote("agent-1", approved=False)
