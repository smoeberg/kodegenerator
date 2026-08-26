"""Belief revision engine for updating hypotheses based on evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from .models import Evidence, EvidenceType, Hypothesis, HypothesisStatus


class BeliefRevisionEngine:
    """Engine responsible for revising confidence and epistemic status of hypotheses."""

    def __init__(
        self,
        supported_threshold: float = 0.8,
        weakened_threshold: float = 0.4,
        rejected_threshold: float = 0.15,
        learning_rate: float = 1.0,
    ) -> None:
        self.supported_threshold = supported_threshold
        self.weakened_threshold = weakened_threshold
        self.rejected_threshold = rejected_threshold
        self.learning_rate = learning_rate

    def incorporate_evidence(
        self,
        hypothesis: Hypothesis,
        evidence: Evidence,
    ) -> Hypothesis:
        """Incorporate new evidence, recompute confidence, and update status."""
        # Ensure evidence references this hypothesis
        if evidence.hypothesis_id != hypothesis.hypothesis_id:
            evidence = evidence.model_copy(update={"hypothesis_id": hypothesis.hypothesis_id})

        if evidence.evidence_type == EvidenceType.SUPPORTING:
            hypothesis.supporting_evidence.append(evidence)
            self._update_confidence(hypothesis, delta=evidence.weight * self.learning_rate)
        elif evidence.evidence_type == EvidenceType.CONTRADICTING:
            hypothesis.contradicting_evidence.append(evidence)
            self._update_confidence(hypothesis, delta=-evidence.weight * self.learning_rate)
        elif evidence.evidence_type == EvidenceType.OBSERVATION:
            pass

        self._revise_status(hypothesis)
        hypothesis.updated_at = datetime.now(timezone.utc)
        return hypothesis

    def add_alternative(
        self,
        hypothesis: Hypothesis,
        alternative_id_or_statement: str,
        supersede: bool = False,
    ) -> Hypothesis:
        """Register an alternative hypothesis and optionally supersede this one."""
        if alternative_id_or_statement not in hypothesis.alternatives:
            hypothesis.alternatives.append(alternative_id_or_statement)
        if supersede:
            hypothesis.status = HypothesisStatus.SUPERSEDED
        hypothesis.updated_at = datetime.now(timezone.utc)
        return hypothesis

    def batch_revise(
        self,
        hypothesis: Hypothesis,
        evidences: List[Evidence],
    ) -> Hypothesis:
        """Incorporate a sequence of evidence items."""
        for ev in evidences:
            self.incorporate_evidence(hypothesis, ev)
        return hypothesis

    def _update_confidence(self, hypothesis: Hypothesis, delta: float) -> None:
        """Update confidence bounded strictly between 0.0 and 1.0."""
        new_conf = hypothesis.confidence + delta
        hypothesis.confidence = max(0.0, min(1.0, round(new_conf, 4)))

    def _revise_status(self, hypothesis: Hypothesis) -> None:
        """Derive hypothesis status based on confidence levels unless terminal/superseded."""
        if hypothesis.status == HypothesisStatus.SUPERSEDED:
            return

        if hypothesis.confidence <= self.rejected_threshold:
            hypothesis.status = HypothesisStatus.REJECTED
        elif hypothesis.confidence < self.weakened_threshold:
            hypothesis.status = HypothesisStatus.WEAKENED
        elif hypothesis.confidence >= self.supported_threshold:
            hypothesis.status = HypothesisStatus.SUPPORTED
        else:
            if hypothesis.status in (HypothesisStatus.PROPOSED, HypothesisStatus.SUPPORTED, HypothesisStatus.WEAKENED):
                hypothesis.status = HypothesisStatus.ACTIVE
