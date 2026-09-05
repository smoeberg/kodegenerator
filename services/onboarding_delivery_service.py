"""Governed delivery bridge from approved onboarding requirements to scaffolding."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from domain.requirements import RequirementsSpecification
from generation.scaffold_engine import ScaffoldEngine, ScaffoldPlan
from phase4.onboarding import OnboardingIntent, OnboardingPurpose


class OnboardingDeliveryError(ValueError):
    """Raised when rewrite delivery is not bound to approved governed inputs."""


@dataclass(frozen=True)
class RewriteScaffoldPlan:
    """Scaffold plan bound to the exact intent and approved parity contract."""

    intent_id: str
    requirements_fingerprint: str
    parity_requirement_ids: tuple[str, ...]
    scaffold: ScaffoldPlan

    @property
    def fingerprint(self) -> str:
        payload = {
            "intent_id": self.intent_id,
            "requirements_fingerprint": self.requirements_fingerprint,
            "parity_requirement_ids": list(self.parity_requirement_ids),
            "scaffold_fingerprint": self.scaffold.fingerprint,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return sha256(encoded.encode("utf-8")).hexdigest()


def plan_modernize_rewrite(
    *,
    intent: OnboardingIntent,
    approved_spec: RequirementsSpecification,
    scaffold_engine: ScaffoldEngine | None = None,
) -> RewriteScaffoldPlan:
    """Create a deterministic scaffold plan only after exact requirements approval."""

    if not isinstance(intent, OnboardingIntent):
        raise TypeError("intent must be an OnboardingIntent")
    if not isinstance(approved_spec, RequirementsSpecification):
        raise TypeError("approved_spec must be a RequirementsSpecification")
    if intent.purpose is not OnboardingPurpose.MODERNIZE_REWRITE:
        raise OnboardingDeliveryError(
            "scaffold planning is only valid for MODERNIZE_REWRITE onboarding"
        )
    if intent.target_stack is None:
        raise OnboardingDeliveryError(
            "MODERNIZE_REWRITE intent has no target_stack"
        )
    if approved_spec.status != "approved" or approved_spec.approval.status != "approved":
        raise OnboardingDeliveryError(
            "rewrite scaffold planning requires an approved requirements specification"
        )

    onboarding = approved_spec.intent.get("onboarding")
    if not isinstance(onboarding, dict):
        raise OnboardingDeliveryError(
            "approved requirements are not bound to onboarding provenance"
        )
    expected = {
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "source_repository": intent.source_repository,
        "organization_id": intent.organization_id,
        "declared_by": intent.declared_by,
        "declared_at": intent.declared_at.isoformat(),
        "content_fingerprint": intent.content_fingerprint,
        "supersedes_intent_id": intent.supersedes_intent_id,
    }
    for key, value in expected.items():
        if onboarding.get(key) != value:
            raise OnboardingDeliveryError(
                f"approved requirements onboarding provenance mismatch: {key}"
            )

    parity_requirement_ids = tuple(
        sorted(requirement.id for requirement in approved_spec.functional_requirements)
    )
    engine = scaffold_engine or ScaffoldEngine()
    scaffold = engine.generate(intent.target_stack)
    return RewriteScaffoldPlan(
        intent_id=intent.intent_id,
        requirements_fingerprint=approved_spec.fingerprint,
        parity_requirement_ids=parity_requirement_ids,
        scaffold=scaffold,
    )
