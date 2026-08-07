"""Deterministic validation gates for requirements specifications."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from domain.requirements import RequirementsSpecification


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    blocking: bool = True
    item_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def blocking(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.blocking)


def validate_requirements(spec: RequirementsSpecification) -> ValidationResult:
    """Validate the requirements contract without consulting external state."""
    issues: list[ValidationIssue] = []

    requirements = (
        *spec.functional_requirements,
        *spec.non_functional_requirements,
        *spec.business_rules,
        *spec.data_requirements,
        *spec.integration_requirements,
        *spec.security_requirements,
        *spec.compliance_requirements,
        *spec.constraints,
    )
    criteria_by_id = {criterion.id: criterion for criterion in spec.acceptance_criteria}

    for requirement in requirements:
        if requirement.priority == "must" and not requirement.acceptance_criteria:
            issues.append(ValidationIssue(
                "MUST_WITHOUT_ACCEPTANCE", f"{requirement.id} is mandatory but has no acceptance criteria", True, requirement.id
            ))
        for criterion_id in requirement.acceptance_criteria:
            if criterion_id not in criteria_by_id:
                issues.append(ValidationIssue(
                    "UNKNOWN_ACCEPTANCE_CRITERION", f"{requirement.id} references unknown criterion {criterion_id}", True, requirement.id
                ))
        if requirement.source == "agent_proposed" and requirement.status == "confirmed":
            issues.append(ValidationIssue(
                "UNAPPROVED_AGENT_REQUIREMENT", f"{requirement.id} is agent-proposed but marked confirmed", True, requirement.id
            ))

    for question in spec.open_questions:
        if question.blocking and question.status not in {"resolved", "closed"}:
            issues.append(ValidationIssue(
                "BLOCKING_QUESTION", f"Blocking question {question.id} remains unresolved", True, question.id
            ))

    if spec.status == "approved" and not spec.approval.content_fingerprint:
        issues.append(ValidationIssue("MISSING_APPROVAL_PROOF", "Approved specification has no content fingerprint"))

    # Every acceptance criterion must point back to an existing requirement.
    known_ids = {item.id for item in requirements}
    for criterion in spec.acceptance_criteria:
        for requirement_id in criterion.requirement_ids:
            if requirement_id not in known_ids:
                issues.append(ValidationIssue(
                    "UNKNOWN_REQUIREMENT_REFERENCE",
                    f"Acceptance criterion {criterion.id} references unknown requirement {requirement_id}",
                    True,
                    criterion.id,
                ))

    return ValidationResult(tuple(issues))
