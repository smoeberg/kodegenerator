"""Minimal, prospective development-governance contracts for Governance v0.

This module governs how DOR itself is changed.  It deliberately does not reuse
``domain.governance`` which models organizational Governance Boards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


GOVERNANCE_V0_VERSION = "governance-v0"
GOVERNANCE_EFFECTIVE_BOUNDARY = "7f91611e2a3f0bf81449551f72a85418f3f27e3d"
GRANDFATHERED_WORK_UNITS = ("WQ-101", "WQ-102", "WQ-103", "WQ-104")


class GovernanceContractError(ValueError):
    """Raised when a Governance v0 contract is malformed."""


class ProblemDecision(str, Enum):
    APPROVED_FOR_DESIGN = "APPROVED_FOR_DESIGN"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"


class ScopeConformance(str, Enum):
    WITHIN_APPROVED_SCOPE = "WITHIN_APPROVED_SCOPE"
    SCOPE_EXPANSION_REQUIRED = "SCOPE_EXPANSION_REQUIRED"


class SolutionDecision(str, Enum):
    APPROVED_FOR_IMPLEMENTATION = "APPROVED_FOR_IMPLEMENTATION"
    REJECTED_WITH_RATIONALE = "REJECTED_WITH_RATIONALE"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    SCOPE_EXPANSION_REQUIRED = "SCOPE_EXPANSION_REQUIRED"


class AuditDecision(str, Enum):
    VERIFIED = "VERIFIED"
    VETO = "VETO"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


SEMANTIC_CHANGE_TRIGGERS = frozenset(
    {
        "domain_meaning",
        "lifecycle",
        "persisted_meaning",
        "consistency_guarantee",
        "concurrency_guarantee",
        "dependency_semantics",
        "authority_boundary",
        "acceptance_invariant",
        "explicit_non_goal",
        "approved_scope",
    }
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GovernanceContractError(f"{name} must be non-empty canonical text")
    return value


def _texts(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise GovernanceContractError(f"{name} must contain text values")
    result = tuple(_text(value, name) for value in values)
    if len(result) != len(set(result)):
        raise GovernanceContractError(f"{name} must not contain duplicates")
    return result


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    return value


def content_fingerprint(value: Any) -> str:
    """Bind an approval to the complete immutable contract content."""
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    encoded = json.dumps(
        _canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProblemBrief:
    problem_id: str
    version: int
    title: str
    observed_problem: str
    impact: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    affected_concepts: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    non_goals: tuple[str, ...] = field(default_factory=tuple)
    proposed_scope: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _text(self.problem_id, "problem_id")
        _text(self.title, "title")
        _text(self.observed_problem, "observed_problem")
        _text(self.impact, "impact")
        if type(self.version) is not int or self.version < 1:
            raise GovernanceContractError("version must be a positive integer")
        for name in (
            "evidence_refs",
            "affected_concepts",
            "constraints",
            "non_goals",
            "proposed_scope",
        ):
            object.__setattr__(self, name, _texts(getattr(self, name), name))

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self)


@dataclass(frozen=True)
class ProblemApproval:
    problem_id: str
    problem_version: int
    problem_fingerprint: str
    decided_by: str
    decision: ProblemDecision
    approved_scope: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    explicit_non_goals: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    def __post_init__(self) -> None:
        _text(self.problem_id, "problem_id")
        _text(self.problem_fingerprint, "problem_fingerprint")
        _text(self.decided_by, "decided_by")
        if len(self.problem_fingerprint) != 64:
            raise GovernanceContractError("problem_fingerprint must be SHA-256 text")
        if type(self.problem_version) is not int or self.problem_version < 1:
            raise GovernanceContractError("problem_version must be positive")
        if not isinstance(self.decision, ProblemDecision):
            raise GovernanceContractError("decision must be a ProblemDecision")
        for name in ("approved_scope", "constraints", "explicit_non_goals"):
            object.__setattr__(self, name, _texts(getattr(self, name), name))
        if self.decision is ProblemDecision.APPROVED_FOR_DESIGN and not self.approved_scope:
            raise GovernanceContractError("approved problem must declare approved_scope")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self)


@dataclass(frozen=True)
class SolutionProposal:
    solution_id: str
    version: int
    problem_id: str
    problem_approval_fingerprint: str
    proposed_design: str
    why_this_is_minimal: str
    scope_conformance: ScopeConformance
    approved_scope: tuple[str, ...]
    explicit_non_goals: tuple[str, ...]
    scope_delta: tuple[str, ...] = field(default_factory=tuple)
    existing_components_reused: tuple[str, ...] = field(default_factory=tuple)
    new_components: tuple[str, ...] = field(default_factory=tuple)
    domain_changes: tuple[str, ...] = field(default_factory=tuple)
    state_machine_changes: tuple[str, ...] = field(default_factory=tuple)
    persistence_changes: tuple[str, ...] = field(default_factory=tuple)
    migration_impact: tuple[str, ...] = field(default_factory=tuple)
    concurrency_semantics: tuple[str, ...] = field(default_factory=tuple)
    authority_changes: tuple[str, ...] = field(default_factory=tuple)
    acceptance_invariants: tuple[str, ...] = field(default_factory=tuple)
    alternatives_considered: tuple[str, ...] = field(default_factory=tuple)
    deferred_items: tuple[str, ...] = field(default_factory=tuple)
    affected_work_units: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for value, name in (
            (self.solution_id, "solution_id"),
            (self.problem_id, "problem_id"),
            (self.problem_approval_fingerprint, "problem_approval_fingerprint"),
            (self.proposed_design, "proposed_design"),
            (self.why_this_is_minimal, "why_this_is_minimal"),
        ):
            _text(value, name)
        if len(self.problem_approval_fingerprint) != 64:
            raise GovernanceContractError("problem_approval_fingerprint must be SHA-256 text")
        if type(self.version) is not int or self.version < 1:
            raise GovernanceContractError("version must be positive")
        if not isinstance(self.scope_conformance, ScopeConformance):
            raise GovernanceContractError("scope_conformance must be ScopeConformance")
        for name in (
            "approved_scope",
            "explicit_non_goals",
            "scope_delta",
            "existing_components_reused",
            "new_components",
            "domain_changes",
            "state_machine_changes",
            "persistence_changes",
            "migration_impact",
            "concurrency_semantics",
            "authority_changes",
            "acceptance_invariants",
            "alternatives_considered",
            "deferred_items",
            "affected_work_units",
        ):
            object.__setattr__(self, name, _texts(getattr(self, name), name))
        if self.scope_conformance is ScopeConformance.WITHIN_APPROVED_SCOPE and self.scope_delta:
            raise GovernanceContractError("within-scope proposal cannot declare scope_delta")
        if self.scope_conformance is ScopeConformance.SCOPE_EXPANSION_REQUIRED and not self.scope_delta:
            raise GovernanceContractError("scope expansion must declare scope_delta")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self)


@dataclass(frozen=True)
class SolutionApproval:
    solution_id: str
    solution_version: int
    solution_fingerprint: str
    problem_approval_fingerprint: str
    decided_by: str
    decision: SolutionDecision
    rationale: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.solution_id, "solution_id"),
            (self.solution_fingerprint, "solution_fingerprint"),
            (self.problem_approval_fingerprint, "problem_approval_fingerprint"),
            (self.decided_by, "decided_by"),
        ):
            _text(value, name)
        if len(self.solution_fingerprint) != 64 or len(self.problem_approval_fingerprint) != 64:
            raise GovernanceContractError("approval fingerprints must be SHA-256 text")
        if type(self.solution_version) is not int or self.solution_version < 1:
            raise GovernanceContractError("solution_version must be positive")
        if not isinstance(self.decision, SolutionDecision):
            raise GovernanceContractError("decision must be SolutionDecision")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self)


@dataclass(frozen=True)
class ArtifactSubmission:
    artifact_version: str
    base_version: str
    changed_files: tuple[str, ...]
    dependency_versions: tuple[str, ...] = field(default_factory=tuple)
    test_claims: tuple[str, ...] = field(default_factory=tuple)
    ci_claims: tuple[str, ...] = field(default_factory=tuple)
    migration_claims: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _text(self.artifact_version, "artifact_version")
        _text(self.base_version, "base_version")
        for name in (
            "changed_files",
            "dependency_versions",
            "test_claims",
            "ci_claims",
            "migration_claims",
        ):
            object.__setattr__(self, name, _texts(getattr(self, name), name))


@dataclass(frozen=True)
class EvidenceReport:
    decision: AuditDecision
    facts_verified: tuple[str, ...]
    mismatches: tuple[str, ...] = field(default_factory=tuple)
    proof_construction_verified: bool = False
    solution_conformance_verified: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.decision, AuditDecision):
            raise GovernanceContractError("decision must be AuditDecision")
        object.__setattr__(self, "facts_verified", _texts(self.facts_verified, "facts_verified"))
        object.__setattr__(self, "mismatches", _texts(self.mismatches, "mismatches"))
        if self.decision is AuditDecision.VERIFIED and self.mismatches:
            raise GovernanceContractError("VERIFIED evidence cannot contain mismatches")
        if self.decision is AuditDecision.VETO and not self.mismatches:
            raise GovernanceContractError("VETO evidence must describe a mismatch")


@dataclass(frozen=True)
class IndependentReview:
    artifact_version: str
    solution_fingerprint: str
    reviewer_id: str
    decision: ReviewDecision
    findings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _text(self.artifact_version, "artifact_version")
        _text(self.solution_fingerprint, "solution_fingerprint")
        _text(self.reviewer_id, "reviewer_id")
        if not isinstance(self.decision, ReviewDecision):
            raise GovernanceContractError("decision must be ReviewDecision")
        object.__setattr__(self, "findings", _texts(self.findings, "findings"))
        if self.decision is ReviewDecision.APPROVED and self.findings:
            raise GovernanceContractError("APPROVED review cannot contain findings")


__all__ = [
    "ArtifactSubmission",
    "AuditDecision",
    "EvidenceReport",
    "GOVERNANCE_EFFECTIVE_BOUNDARY",
    "GOVERNANCE_V0_VERSION",
    "GRANDFATHERED_WORK_UNITS",
    "GovernanceContractError",
    "IndependentReview",
    "ProblemApproval",
    "ProblemBrief",
    "ProblemDecision",
    "ReviewDecision",
    "SEMANTIC_CHANGE_TRIGGERS",
    "ScopeConformance",
    "SolutionApproval",
    "SolutionDecision",
    "SolutionProposal",
    "content_fingerprint",
]
