"""Canonical requirements-domain model for P3-17.

The requirements model is deliberately independent of persistence and AI
providers. It represents the human-approved contract consumed downstream by
architecture, distribution, implementation, testing and audit agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, ClassVar, Mapping

ID_RE = re.compile(r"^(FR|NFR|BR|DR|IR|SR|CR|CON|AC|ASM|Q|STK|ACT)-[0-9]{3,}$")

STATUSES = frozenset({"draft", "clarification_required", "review", "approved", "superseded", "rejected"})
PRIORITIES = frozenset({"must", "should", "could", "wont"})
PROVENANCE = frozenset({"human", "conversation", "imported", "agent_proposed", "system_derived"})


class RequirementsValidationError(ValueError):
    """Raised when a requirements object cannot be represented safely."""


@dataclass(frozen=True)
class TraceLink:
    source_id: str
    target_id: str
    relation: str


@dataclass(frozen=True)
class Requirement:
    id: str
    statement: str
    source: str
    status: str = "confirmed"
    priority: str | None = None
    acceptance_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.id)
        _nonempty(self.statement, "statement")
        if self.source not in PROVENANCE:
            raise RequirementsValidationError(f"Invalid provenance: {self.source}")
        if self.priority is not None and self.priority not in PRIORITIES:
            raise RequirementsValidationError(f"Invalid priority: {self.priority}")
        _nonempty_ids(self.acceptance_criteria, "acceptance_criteria")


@dataclass(frozen=True)
class AcceptanceCriterion:
    id: str
    statement: str
    status: str = "confirmed"
    requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.id)
        _nonempty(self.statement, "statement")
        _nonempty_ids(self.requirement_ids, "requirement_ids")


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    question: str
    blocking: bool
    owner: str
    status: str = "open"
    resolution: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.id)
        _nonempty(self.question, "question")
        _nonempty(self.owner, "owner")
        if self.blocking and self.status not in {"resolved", "closed"}:
            return


@dataclass(frozen=True)
class Assumption:
    id: str
    statement: str
    source: str
    confidence: str = "medium"
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        _validate_id(self.id)
        _nonempty(self.statement, "statement")
        if self.source not in PROVENANCE:
            raise RequirementsValidationError(f"Invalid assumption provenance: {self.source}")


@dataclass(frozen=True)
class Approval:
    status: str = "pending"
    specification_id: str | None = None
    version: str | None = None
    content_fingerprint: str | None = None
    approver_id: str | None = None
    approved_at: datetime | None = None
    validation_result: str | None = None


@dataclass(frozen=True)
class RequirementsSpecification:
    schema_version: str
    specification_id: str
    project: Mapping[str, Any]
    version: str
    status: str
    intent: Mapping[str, Any]
    stakeholders: tuple[Mapping[str, Any], ...] = ()
    actors: tuple[Mapping[str, Any], ...] = ()
    functional_requirements: tuple[Requirement, ...] = ()
    non_functional_requirements: tuple[Requirement, ...] = ()
    business_rules: tuple[Requirement, ...] = ()
    data_requirements: tuple[Requirement, ...] = ()
    integration_requirements: tuple[Requirement, ...] = ()
    security_requirements: tuple[Requirement, ...] = ()
    compliance_requirements: tuple[Requirement, ...] = ()
    constraints: tuple[Requirement, ...] = ()
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    traceability: tuple[TraceLink, ...] = ()
    approval: Approval = field(default_factory=Approval)
    previous_version: str | None = None

    REQUIRED_SECTIONS: ClassVar[tuple[str, ...]] = (
        "schema_version", "specification_id", "project", "version", "status", "intent",
        "stakeholders", "actors", "functional_requirements", "non_functional_requirements",
        "business_rules", "data_requirements", "integration_requirements", "security_requirements",
        "compliance_requirements", "constraints", "acceptance_criteria", "assumptions",
        "open_questions", "traceability", "approval",
    )

    def __post_init__(self) -> None:
        _nonempty(self.schema_version, "schema_version")
        _nonempty(self.specification_id, "specification_id")
        _nonempty(self.version, "version")
        if self.status not in STATUSES:
            raise RequirementsValidationError(f"Invalid specification status: {self.status}")
        if not isinstance(self.project, Mapping) or not self.project.get("name"):
            raise RequirementsValidationError("project.name is required")
        if not isinstance(self.intent, Mapping):
            raise RequirementsValidationError("intent must be an object")
        _validate_unique_ids(self.all_items())
        if self.approval.status == "approved":
            if self.approval.specification_id != self.specification_id or self.approval.version != self.version:
                raise RequirementsValidationError("Approval must identify the exact specification version")
            if not self.approval.content_fingerprint or not self.approval.approver_id or not self.approval.approved_at:
                raise RequirementsValidationError("Approved specification requires fingerprint, approver and timestamp")

    def all_items(self) -> tuple[Any, ...]:
        return (
            *self.functional_requirements, *self.non_functional_requirements, *self.business_rules,
            *self.data_requirements, *self.integration_requirements, *self.security_requirements,
            *self.compliance_requirements, *self.constraints, *self.acceptance_criteria,
            *self.assumptions, *self.open_questions,
        )

    def canonical_dict(self) -> dict[str, Any]:
        """Return canonical JSON-compatible content excluding mutable approval proof."""
        def plain(value: Any) -> Any:
            if hasattr(value, "__dataclass_fields__"):
                return {k: plain(getattr(value, k)) for k in value.__dataclass_fields__ if k not in {"approval"}}
            if isinstance(value, Mapping):
                return {str(k): plain(value[k]) for k in sorted(value)}
            if isinstance(value, (tuple, list)):
                return [plain(v) for v in value]
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat()
            return value
        data = plain(self)
        data.pop("approval", None)
        return data

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RequirementsValidationError(f"{field_name} must be non-empty")


def _validate_id(value: str) -> None:
    if not ID_RE.match(value):
        raise RequirementsValidationError(f"Invalid stable requirement id: {value}")


def _nonempty_ids(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        _validate_id(value)


def _validate_unique_ids(items: tuple[Any, ...]) -> None:
    ids = [item.id for item in items if hasattr(item, "id")]
    if len(ids) != len(set(ids)):
        raise RequirementsValidationError("Requirement identifiers must be globally unique")


def approval_for(spec: RequirementsSpecification, approver_id: str, approved_at: datetime | None = None) -> Approval:
    """Build an approval proof for an already validated specification."""
    _nonempty(approver_id, "approver_id")
    return Approval(
        status="approved",
        specification_id=spec.specification_id,
        version=spec.version,
        content_fingerprint=spec.fingerprint,
        approver_id=approver_id,
        approved_at=approved_at or datetime.now(timezone.utc),
        validation_result="passed",
    )
