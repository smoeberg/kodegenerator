"""Application service for requirements validation and human approval."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from domain.requirements import Approval, RequirementsSpecification, approval_for
from services.requirements_validator import ValidationResult, validate_requirements


class RequirementsApprovalError(ValueError):
    """Raised when an approval gate is attempted before validation succeeds."""


def validate(spec: RequirementsSpecification) -> ValidationResult:
    return validate_requirements(spec)


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
        raise RequirementsApprovalError("Only active draft/review specifications may be rejected")
    return replace(spec, status="rejected", approval=Approval(status="rejected"))
