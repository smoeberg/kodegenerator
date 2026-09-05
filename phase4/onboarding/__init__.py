"""Canonical onboarding-intent contract and deterministic audit objectives."""

from .models import (
    OnboardingContractError,
    OnboardingIntent,
    OnboardingIntentDraft,
    OnboardingPurpose,
)
from .objectives import (
    AUDIT_ONLY_OBJECTIVES,
    EXTEND_OBJECTIVES,
    MODERNIZE_REWRITE_OBJECTIVES,
    objectives_for,
)

__all__ = [
    "AUDIT_ONLY_OBJECTIVES",
    "EXTEND_OBJECTIVES",
    "MODERNIZE_REWRITE_OBJECTIVES",
    "OnboardingContractError",
    "OnboardingIntent",
    "OnboardingIntentDraft",
    "OnboardingPurpose",
    "objectives_for",
]

__version__ = "1.0.0"
