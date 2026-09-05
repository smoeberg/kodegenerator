"""Application service for requirements validation and human approval."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from domain.requirements import Approval, RequirementsSpecification, approval_for
from phase4.onboarding import (
    ONBOARDING_INTENT_CONTEXT_KEY,
    OnboardingIntent,
    objectives_for,
)
from phase4.project_audit.models import ProjectAuditReport
from services.requirements_validator import ValidationResult, validate_requirements


class RequirementsApprovalError(ValueError):
    """Raised when an approval gate is attempted before validation succeeds."""


class RequirementsIntentBindingError(ValueError):
    """Raised when requirements provenance does not match a governed audit intent."""


def validate(spec: RequirementsSpecification) -> ValidationResult:
    return validate_requirements(spec)


def bind_onboarding_intent(
    spec: RequirementsSpecification,
    *,
    report: ProjectAuditReport,
    intent: OnboardingIntent,
) -> RequirementsSpecification:
    """Bind audited onboarding provenance before the human approval fingerprint.

    This function does not invent requirements from audit findings. It only
    proves that the supplied Project Audit report was executed for the exact
    immutable onboarding intent and then records that provenance in the
    canonical ``RequirementsSpecification.intent`` section.
    """

    if not isinstance(spec, RequirementsSpecification):
        raise TypeError("spec must be a RequirementsSpecification")
    if not isinstance(report, ProjectAuditReport):
        raise TypeError("report must be a ProjectAuditReport")
    if not isinstance(intent, OnboardingIntent):
        raise TypeError("intent must be an OnboardingIntent")
    if spec.status in {"approved", "superseded", "rejected"}:
        raise RequirementsIntentBindingError(
            "onboarding intent must be bound before terminal requirements state"
        )

    _assert_report_intent_binding(report, intent)
    metadata = onboarding_intent_metadata(report=report, intent=intent)
    current = dict(spec.intent)
    existing = current.get("onboarding")
    if existing is not None and existing != metadata:
        raise RequirementsIntentBindingError(
            "requirements specification is already bound to different onboarding provenance"
        )
    current["onboarding"] = metadata
    return replace(spec, intent=current)


def onboarding_intent_metadata(
    *,
    report: ProjectAuditReport,
    intent: OnboardingIntent,
) -> dict[str, Any]:
    """Return the compact immutable provenance recorded in requirements."""

    _assert_report_intent_binding(report, intent)
    return {
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "source_repository": intent.source_repository,
        "organization_id": intent.organization_id,
        "declared_by": intent.declared_by,
        "declared_at": intent.declared_at.isoformat(),
        "content_fingerprint": intent.content_fingerprint,
        "supersedes_intent_id": intent.supersedes_intent_id,
        "audit_report_id": report.report_id,
        "audit_request_fingerprint": report.request_fingerprint,
    }


def approve(
    spec: RequirementsSpecification,
    approver_id: str,
    approved_at: datetime | None = None,
) -> RequirementsSpecification:
    """Approve only a valid review specification; never mutate the input."""
    if spec.status != "review":
        raise RequirementsApprovalError("Only specifications in review may be approved")

    result = validate_requirements(spec)
    if not result.valid:
        codes = ", ".join(issue.code for issue in result.issues)
        raise RequirementsApprovalError(f"Requirements validation failed: {codes}")

    approval = approval_for(spec, approver_id, approved_at)
    return replace(spec, status="approved", approval=approval)


def reject(spec: RequirementsSpecification) -> RequirementsSpecification:
    """Reject a draft/review specification without modifying its history."""
    if spec.status not in {"draft", "clarification_required", "review"}:
        raise RequirementsApprovalError(
            "Only active draft/review specifications may be rejected"
        )
    return replace(spec, status="rejected", approval=Approval(status="rejected"))


def _assert_report_intent_binding(
    report: ProjectAuditReport,
    intent: OnboardingIntent,
) -> None:
    if report.request.resource != intent.source_repository:
        raise RequirementsIntentBindingError(
            "audit report repository does not match onboarding intent"
        )
    expected_objectives = tuple(sorted(objectives_for(intent.purpose)))
    if report.request.objectives != expected_objectives:
        raise RequirementsIntentBindingError(
            "audit report objectives do not match onboarding purpose"
        )

    matches = [
        item
        for item in report.request.context_packet.items
        if item.source == "onboarding-intent"
        and item.key == ONBOARDING_INTENT_CONTEXT_KEY
    ]
    if len(matches) != 1:
        raise RequirementsIntentBindingError(
            "audit report does not contain exactly one onboarding intent binding"
        )
    if matches[0].canonical()["value"] != intent.canonical():
        raise RequirementsIntentBindingError(
            "audit report onboarding provenance does not match supplied intent"
        )
