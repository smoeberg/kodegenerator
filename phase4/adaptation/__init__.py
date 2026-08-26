"""Phase 4 Adaptation Module.

Provides strategy fingerprinting, failure classification, and anti-tube triggers
to prevent unviable retry loops and force epistemic hypothesis pivots.
"""

from .anti_tube import AntiTubeTrigger
from .classifier import FailureClassifier
from .fingerprint import StrategyFingerprinter
from .models import (
    AdaptationAction,
    AdaptationResult,
    ExecutionFailure,
    FailureCategory,
    StrategyFingerprint,
)

__all__ = [
    "StrategyFingerprint",
    "StrategyFingerprinter",
    "ExecutionFailure",
    "FailureCategory",
    "AdaptationAction",
    "AdaptationResult",
    "FailureClassifier",
    "AntiTubeTrigger",
]
