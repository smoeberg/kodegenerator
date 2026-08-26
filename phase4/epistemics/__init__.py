"""Phase 4 Epistemics module.

Provides structured models and reasoning engine for evidence-based hypotheses.
"""

from .engine import BeliefRevisionEngine
from .models import Evidence, EvidenceType, Hypothesis, HypothesisStatus

__all__ = [
    "Hypothesis",
    "HypothesisStatus",
    "Evidence",
    "EvidenceType",
    "BeliefRevisionEngine",
]
