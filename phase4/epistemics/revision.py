"""Belief revision engine for updating hypothesis confidence and status based on evidence."""
from __future__ import annotations

from phase4.epistemics.models import Evidence, Hypothesis, HypothesisStatus


class BeliefRevisionEngine:
    """Engine responsible for updating agent beliefs when new evidence arrives."""

    @staticmethod
    def add_evidence(hypothesis: Hypothesis, evidence: Evidence) -> Hypothesis:
        """Add new evidence to a hypothesis, recalculate confidence, and update status."""
        if evidence.supports:
            hypothesis.supporting_evidence.append(evidence)
        else:
            hypothesis.contradicting_evidence.append(evidence)

        # Recalculate confidence using weighted evidence
        sup_weight = sum(e.confidence for e in hypothesis.supporting_evidence)
        con_weight = sum(e.confidence for e in hypothesis.contradicting_evidence)
        total_weight = sup_weight + con_weight

        if total_weight > 0:
            raw_conf = sup_weight / total_weight
            # Smooth towards center or bound
            hypothesis.confidence = round(max(0.0, min(1.0, raw_conf)), 3)
        else:
            hypothesis.confidence = 0.5

        # Update status based on confidence and evidence volume
        total_count = len(hypothesis.supporting_evidence) + len(hypothesis.contradicting_evidence)
        
        if total_count >= 2 and hypothesis.confidence >= 0.8:
            hypothesis.status = HypothesisStatus.SUPPORTED
        elif total_count >= 2 and hypothesis.confidence <= 0.2:
            hypothesis.status = HypothesisStatus.REJECTED
        elif hypothesis.confidence < 0.4:
            hypothesis.status = HypothesisStatus.WEAKENED
        elif hypothesis.confidence >= 0.6:
            hypothesis.status = HypothesisStatus.ACTIVE

        return hypothesis
