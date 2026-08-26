"""Unit tests for the epistemic core and belief revision engine."""
from phase4.epistemics.models import Evidence, Hypothesis, HypothesisStatus
from phase4.epistemics.revision import BeliefRevisionEngine


def test_hypothesis_initialization():
    h = Hypothesis(
        hypothesis_id="h-1",
        task_id="task-100",
        statement="Use SQLAlchemy 2.x async session factory"
    )
    assert h.status == HypothesisStatus.PROPOSED
    assert h.confidence == 0.5
    assert len(h.supporting_evidence) == 0


def test_belief_revision_supporting():
    h = Hypothesis(
        hypothesis_id="h-1",
        task_id="task-100",
        statement="Use SQLAlchemy 2.x async session factory"
    )
    e1 = Evidence(evidence_id="e-1", source="benchmark", content="Fast async query", supports=True, confidence=0.9)
    e2 = Evidence(evidence_id="e-2", source="docs", content="Official recommendation", supports=True, confidence=0.8)

    BeliefRevisionEngine.add_evidence(h, e1)
    BeliefRevisionEngine.add_evidence(h, e2)

    assert h.confidence > 0.8
    assert h.status == HypothesisStatus.SUPPORTED
    assert len(h.supporting_evidence) == 2


def test_belief_revision_contradicting():
    h = Hypothesis(
        hypothesis_id="h-2",
        task_id="task-100",
        statement="Monolithic single-thread execution"
    )
    e1 = Evidence(evidence_id="e-3", source="load-test", content="CPU bottleneck", supports=False, confidence=0.9)
    e2 = Evidence(evidence_id="e-4", source="profiler", content="Thread blocking detected", supports=False, confidence=0.8)

    BeliefRevisionEngine.add_evidence(h, e1)
    BeliefRevisionEngine.add_evidence(h, e2)

    assert h.confidence < 0.3
    assert h.status == HypothesisStatus.REJECTED
    assert len(h.contradicting_evidence) == 2
