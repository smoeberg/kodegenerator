"""Unit tests for Phase 4 Epistemics module."""

import pytest
from pydantic import ValidationError

from phase4.epistemics import (
    BeliefRevisionEngine,
    Evidence,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
)


def test_hypothesis_initialization_defaults():
    """Test standard initialization and default field values."""
    hyp = Hypothesis(
        task_id="task-101",
        statement="Database connection timeout is caused by pool exhaustion",
    )

    assert hyp.task_id == "task-101"
    assert hyp.statement == "Database connection timeout is caused by pool exhaustion"
    assert hyp.status == HypothesisStatus.PROPOSED
    assert hyp.confidence == 0.5
    assert hyp.supporting_evidence == []
    assert hyp.contradicting_evidence == []
    assert hyp.alternatives == []
    assert hyp.hypothesis_id is not None


def test_hypothesis_validation_constraints():
    """Test validation constraints on confidence and status enum."""
    with pytest.raises(ValidationError):
        Hypothesis(
            task_id="task-102",
            statement="Invalid confidence hypothesis",
            confidence=1.5,
        )

    with pytest.raises(ValidationError):
        Hypothesis(
            task_id="task-102",
            statement="Negative confidence hypothesis",
            confidence=-0.1,
        )


def test_belief_revision_supporting_evidence_to_supported():
    """Test confidence increase and status transition to SUPPORTED upon strong evidence."""
    engine = BeliefRevisionEngine(supported_threshold=0.8)
    hyp = Hypothesis(
        task_id="task-103",
        statement="Memory leak is present in worker queue",
        confidence=0.5,
    )

    ev1 = Evidence(
        hypothesis_id=hyp.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.2,
        source="profiler_logs",
        description="Heap memory usage continuously climbing without GC collection",
    )
    engine.incorporate_evidence(hyp, ev1)
    assert hyp.confidence == 0.7
    assert hyp.status == HypothesisStatus.ACTIVE
    assert len(hyp.supporting_evidence) == 1

    ev2 = Evidence(
        hypothesis_id=hyp.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.2,
        source="leak_detector",
        description="Unclosed socket handles confirmed in memory dump",
    )
    engine.incorporate_evidence(hyp, ev2)
    assert hyp.confidence == 0.9
    assert hyp.status == HypothesisStatus.SUPPORTED
    assert len(hyp.supporting_evidence) == 2


def test_belief_revision_contradicting_evidence_to_weakened_and_rejected():
    """Test confidence decrease and status transition to WEAKENED and REJECTED."""
    engine = BeliefRevisionEngine(weakened_threshold=0.4, rejected_threshold=0.15)
    hyp = Hypothesis(
        task_id="task-104",
        statement="DNS resolution is failing",
        confidence=0.5,
    )

    ev_contradict1 = Evidence(
        hypothesis_id=hyp.hypothesis_id,
        evidence_type=EvidenceType.CONTRADICTING,
        weight=0.2,
        source="dig_output",
        description="DNS query resolved accurately in 2ms",
    )
    engine.incorporate_evidence(hyp, ev_contradict1)
    assert hyp.confidence == 0.3
    assert hyp.status == HypothesisStatus.WEAKENED
    assert len(hyp.contradicting_evidence) == 1

    ev_contradict2 = Evidence(
        hypothesis_id=hyp.hypothesis_id,
        evidence_type=EvidenceType.CONTRADICTING,
        weight=0.25,
        source="core_dns_metrics",
        description="CoreDNS reports 100% success rate",
    )
    engine.incorporate_evidence(hyp, ev_contradict2)
    assert hyp.confidence == 0.05
    assert hyp.status == HypothesisStatus.REJECTED
    assert len(hyp.contradicting_evidence) == 2


def test_belief_revision_alternatives_and_superseded():
    """Test adding alternatives and superseding hypotheses."""
    engine = BeliefRevisionEngine()
    hyp = Hypothesis(
        task_id="task-105",
        statement="CPU throttling due to temperature",
        confidence=0.5,
    )

    engine.add_alternative(
        hyp,
        alternative_id_or_statement="hyp-105-b: CPU throttling due to cgroup quota",
        supersede=True,
    )

    assert "hyp-105-b: CPU throttling due to cgroup quota" in hyp.alternatives
    assert hyp.status == HypothesisStatus.SUPERSEDED


def test_belief_revision_batch_revise():
    """Test batch revision of multiple mixed evidence items."""
    engine = BeliefRevisionEngine()
    hyp = Hypothesis(
        task_id="task-106",
        statement="Network partition between node-A and node-B",
        confidence=0.5,
    )

    evidences = [
        Evidence(
            hypothesis_id=hyp.hypothesis_id,
            evidence_type=EvidenceType.SUPPORTING,
            weight=0.3,
            source="ping_probe",
            description="100% packet loss on direct interface",
        ),
        Evidence(
            hypothesis_id=hyp.hypothesis_id,
            evidence_type=EvidenceType.CONTRADICTING,
            weight=0.1,
            source="bgp_route",
            description="Alternative BGP route is still announcing health",
        ),
    ]

    engine.batch_revise(hyp, evidences)
    assert hyp.confidence == 0.7
    assert len(hyp.supporting_evidence) == 1
    assert len(hyp.contradicting_evidence) == 1
    assert hyp.status == HypothesisStatus.ACTIVE
