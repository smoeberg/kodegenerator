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

ONBOARDING_INTENT_CONTEXT_KEY = "onboarding-intent"

__all__ = [
    "AUDIT_ONLY_OBJECTIVES",
    "EXTEND_OBJECTIVES",
    "MODERNIZE_REWRITE_OBJECTIVES",
    "ONBOARDING_INTENT_CONTEXT_KEY",
    "OnboardingContractError",
    "OnboardingIntent",
    "OnboardingIntentDraft",
    "OnboardingPurpose",
    "objectives_for",
]

__version__ = "1.0.0"
