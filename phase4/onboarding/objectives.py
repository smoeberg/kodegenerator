"""Deterministic onboarding-purpose to Project Audit objective mapping."""
from __future__ import annotations

from .models import OnboardingContractError, OnboardingPurpose


EXTEND_OBJECTIVES = (
    "map integration points and existing conventions in the current stack",
    "identify undocumented technical debt and dependency hotspots",
    "propose an initial epic breakdown that builds on the existing architecture",
)

MODERNIZE_REWRITE_OBJECTIVES = (
    "extract externally observable behavior independent of implementation",
    "map the existing test suite to parity acceptance criteria",
    "identify source-language constructs with no direct target-stack equivalent",
    "flag behavior that cannot be verified as parity from available evidence",
)

AUDIT_ONLY_OBJECTIVES = (
    "assess primary language, architecture pattern and test coverage",
    "surface risks that would affect any future onboarding decision",
)

_OBJECTIVES_BY_PURPOSE = {
    OnboardingPurpose.EXTEND: EXTEND_OBJECTIVES,
    OnboardingPurpose.MODERNIZE_REWRITE: MODERNIZE_REWRITE_OBJECTIVES,
    OnboardingPurpose.AUDIT_ONLY: AUDIT_ONLY_OBJECTIVES,
}


def objectives_for(purpose: OnboardingPurpose) -> tuple[str, ...]:
    """Return the closed objective set for one declared onboarding purpose.

    A plain string is deliberately rejected even though ``OnboardingPurpose``
    is string-like. Callers must cross the typed purpose boundary rather than
    reintroducing free-text interpretation.
    """

    if not isinstance(purpose, OnboardingPurpose):
        raise OnboardingContractError("purpose must be a declared OnboardingPurpose")
    return _OBJECTIVES_BY_PURPOSE[purpose]
