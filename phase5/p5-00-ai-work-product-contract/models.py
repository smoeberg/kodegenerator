"""Normative P5-00 domain objects.

The objects are immutable snapshots. Lifecycle state is deliberately not a
mutable field on WorkProductSubmission; it is derived from append-only events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional, Tuple

from .fingerprinting import fingerprint


class ArtifactType(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    MIGRATION = "migration"
    SCHEMA = "schema"
    TEST_SUITE = "test-suite"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    REPOSITORY_STATE = "repository-state"


class EvidenceAuthority(str, Enum):
    CANDIDATE = "candidate"
    GOVERNED = "governed"


@dataclass(frozen=True)
class ArtifactRequirement:
    artifact_id: str
    artifact_type: ArtifactType
    location: str
    required: bool = True
    integrity_rule: str = "sha256"
    verification_method: str = "exact-content-fingerprint"

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.location:
            raise ValueError("artifact_id and location are required")
        if self.integrity_rule not in {"sha256", "exact-content-fingerprint"}:
            raise ValueError("unsupported integrity_rule")


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    requirement: str
    predicate: str
    verifier: str
    evidence_source: str
    mandatory: bool = True

    def __post_init__(self) -> None:
        for name, value in (("criterion_id", self.criterion_id), ("requirement", self.requirement), ("predicate", self.predicate), ("verifier", self.verifier), ("evidence_source", self.evidence_source)):
            if not value:
                raise ValueError(f"{name} is required")


@dataclass(frozen=True)
class VerificationProcedure:
    procedure_id: str
    verifier: str
    method: str
    version: str


@dataclass(frozen=True)
class AIWorkProductContract:
    contract_id: str
    contract_version: str
    product_type: str
    product_location: str
    intent: str
    inputs: Tuple[str, ...]
    required_artifacts: Tuple[ArtifactRequirement, ...]
    outputs: Tuple[str, ...]
    acceptance_criteria: Tuple[AcceptanceCriterion, ...]
    verification_procedure: VerificationProcedure
    regression_requirements: Tuple[str, ...]
    required_capabilities: Tuple[str, ...]
    authority_boundaries: Tuple[str, ...]
    forbidden_actions: Tuple[str, ...]
    forbidden_outputs: Tuple[str, ...]
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.contract_id or not self.contract_version:
            raise ValueError("contract identity is required")
        if self.verification_procedure.verifier != "p3-20":
            raise ValueError("P5-00 requires P3-20 as verification authority")
        if not self.required_artifacts:
            raise ValueError("contract must declare required artifacts")
        criterion_ids = [c.criterion_id for c in self.acceptance_criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion_id values must be unique")
        artifact_ids = [a.artifact_id for a in self.required_artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact_id values must be unique")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "required_artifacts", tuple(self.required_artifacts))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "acceptance_criteria", tuple(self.acceptance_criteria))
        object.__setattr__(self, "regression_requirements", tuple(self.regression_requirements))
        object.__setattr__(self, "required_capabilities", tuple(self.required_capabilities))
        object.__setattr__(self, "authority_boundaries", tuple(self.authority_boundaries))
        object.__setattr__(self, "forbidden_actions", tuple(self.forbidden_actions))
        object.__setattr__(self, "forbidden_outputs", tuple(self.forbidden_outputs))
        payload = {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "product_type": self.product_type,
            "product_location": self.product_location,
            "intent": self.intent,
            "inputs": self.inputs,
            "required_artifacts": self.required_artifacts,
            "outputs": self.outputs,
            "acceptance_criteria": self.acceptance_criteria,
            "verification_procedure": self.verification_procedure,
            "regression_requirements": self.regression_requirements,
            "required_capabilities": self.required_capabilities,
            "authority_boundaries": self.authority_boundaries,
            "forbidden_actions": self.forbidden_actions,
            "forbidden_outputs": self.forbidden_outputs,
        }
        object.__setattr__(self, "contract_fingerprint", fingerprint(payload))


@dataclass(frozen=True)
class RepositoryState:
    repository: str
    revision: str
    tree_fingerprint: str
    clean: bool


@dataclass(frozen=True)
class SubmittedArtifact:
    artifact_id: str
    artifact_type: ArtifactType
    location: str
    content_fingerprint: str
    size: Optional[int] = None


@dataclass(frozen=True)
class CandidateEvidence:
    evidence_id: str
    criterion_id: str
    source: str
    payload_fingerprint: str
    authority: EvidenceAuthority = EvidenceAuthority.CANDIDATE

    def __post_init__(self) -> None:
        if self.authority is not EvidenceAuthority.CANDIDATE:
            raise ValueError("agent submissions may only create candidate evidence")


@dataclass(frozen=True)
class WorkProductSubmission:
    submission_id: str
    contract_fingerprint: str
    agent_id: str
    repository_state: RepositoryState
    artifacts: Tuple[SubmittedArtifact, ...]
    candidate_evidence: Tuple[CandidateEvidence, ...]
    submitted_at: datetime

    def __post_init__(self) -> None:
        if not self.submission_id or not self.contract_fingerprint or not self.agent_id:
            raise ValueError("submission identity, contract fingerprint and agent are required")
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "candidate_evidence", tuple(self.candidate_evidence))
        if self.submitted_at.tzinfo is None:
            object.__setattr__(self, "submitted_at", self.submitted_at.replace(tzinfo=timezone.utc))


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    passed: bool
    evidence_ids: Tuple[str, ...]
    verifier: str
    reason: str


@dataclass(frozen=True)
class VerificationDecision:
    decision_id: str
    submission_id: str
    contract_fingerprint: str
    verifier: str
    passed: bool
    criterion_results: Tuple[CriterionResult, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.verifier != "p3-20":
            raise ValueError("only p3-20 may issue verification decisions")
        if self.decided_at.tzinfo is None:
            object.__setattr__(self, "decided_at", self.decided_at.replace(tzinfo=timezone.utc))
