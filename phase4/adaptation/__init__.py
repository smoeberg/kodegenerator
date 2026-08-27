"""Phase 4 Adaptation Module.

Provides strategy fingerprinting, failure classification, anti-tube triggers,
and quality-first hybrid routing across multi-tier LLM providers.
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
from .quality_router import (
    ModelEndpoint,
    ModelTier,
    NoAvailableProviderError,
    Provider,
    QualityFirstRouter,
    RouterConfigurationError,
    RoutingDecision,
    RoutingRequest,
    TaskSensitivity,
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
    "ModelTier",
    "Provider",
    "TaskSensitivity",
    "ModelEndpoint",
    "RoutingRequest",
    "RoutingDecision",
    "QualityFirstRouter",
    "RouterConfigurationError",
    "NoAvailableProviderError",
]
