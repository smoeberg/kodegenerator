"""Immutable contracts for the Phase 4B-2 Project Audit Agent.

The audit agent examines a bounded, content-addressed repository snapshot and
returns evidence-backed advice. It cannot modify the repository, grant
authority, or issue P3-20's authoritative PASS/FAIL result.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath

from phase4.authority.models import AuthorityRequest
from phase4.context_packet.models import ContextPacket
from phase4.execution.models import ExecutionRequest

PROJECT_AUDIT_ACTION = "project.audit"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain outer whitespace")
    return value


def _validate_repository_path(path: str) -> str:
    _validate_non_empty(path, "repository path")
    if "\\" in path:
        raise ValueError("repository paths must be canonical POSIX paths")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or path.startswith("/") or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts) or candidate.as_posix() != path:
        raise ValueError("repository paths must be canonical POSIX paths")
    return path


class EvidenceKind(str, Enum):
    SOURCE="source"; TEST="test"; CI="ci"; DEPLOYMENT="deployment"; MIGRATION="migration"; REQUIREMENT="requirement"; ARCHITECTURE="architecture"; CONFIGURATION="configuration"; OTHER="other"
class FindingClassification(str, Enum): FACT="fact"; INFERENCE="inference"; UNKNOWN="unknown"
class FindingSeverity(str, Enum): INFO="info"; LOW="low"; MEDIUM="medium"; HIGH="high"; CRITICAL="critical"
class EvidencePredicate(str, Enum): PATH_EXISTS="path_exists"; PATH_ABSENT="path_absent"; TEXT_CONTAINS="text_contains"; TEXT_ABSENT="text_absent"; SHA256_EQUALS="sha256_equals"
class MaturityLevel(str, Enum): CONTRACT_COMPLETE="contract_complete"; INTEGRATED="integrated"; OPERATIONAL="operational"; E2E_VERIFIED="e2e_verified"; PRODUCTION_READY="production_ready"
class MaturityStatus(str, Enum): ACHIEVED="achieved"; GAPPED="gapped"; UNKNOWN="unknown"
class AuditRecommendation(str, Enum): CONTINUE="continue"; CONTINUE_WITH_GAPS="continue_with_gaps"; REPLAN="replan"; ESCALATE="escalate"

@dataclass(frozen=True, order=True)
class ManifestEntry:
    path: str; sha256: str
    def __post_init__(self):
        object.__setattr__(self,"path",_validate_repository_path(self.path))
        if not isinstance(self.sha256,str) or not _HEX_DIGEST.fullmatch(self.sha256): raise ValueError("manifest SHA-256 must be 64 lowercase hex")
    def canonical(self): return {"path":self.path,"sha256":self.sha256}

@dataclass(frozen=True)
class RepositoryManifest:
    repository: str; commit_sha: str; entries: tuple[ManifestEntry,...]; complete: bool=True; manifest_id: str=field(init=False)
    def __post_init__(self):
        _validate_non_empty(self.repository,"repository")
        if not isinstance(self.commit_sha,str) or not _REVISION.fullmatch(self.commit_sha): raise ValueError("commit_sha must be 7-64 lowercase hexadecimal characters")
        if type(self.complete) is not bool or not self.complete: raise ValueError("whole-project audit requires a complete tracked-file manifest")
        if any(not isinstance(e,ManifestEntry) for e in self.entries): raise TypeError("manifest entries must be ManifestEntry values")
        entries=tuple(sorted(self.entries,key=lambda x:x.path)); paths=tuple(e.path for e in entries)
        if not entries or len(paths)!=len(set(paths)): raise ValueError("manifest paths must be unique and non-empty")
        object.__setattr__(self,"entries",entries)
        object.__setattr__(self,"manifest_id",_canonical_digest({"repository":self.repository,"commit_sha":self.commit_sha,"complete":self.complete,"entries":[e.canonical() for e in entries]}))

@dataclass(frozen=True, order=True)
class EvidenceArtifact:
    path: str; kind: EvidenceKind; sha256: str; byte_count: int; content: str|None=None
    def __post_init__(self):
        object.__setattr__(self,"path",_validate_repository_path(self.path))
        if not isinstance(self.kind,EvidenceKind): raise TypeError("kind must be an EvidenceKind")
        if not isinstance(self.sha256,str) or not _HEX_DIGEST.fullmatch(self.sha256): raise ValueError("artifact SHA-256 must be 64 lowercase hex")
        if type(self.byte_count) is not int or self.byte_count<0: raise ValueError("byte_count must be a non-negative integer")
        if self.content is not None:
            if not isinstance(self.content,str): raise TypeError("artifact content must be text or None")
            encoded=self.content.encode("utf-8")
            if len(encoded)!=self.byte_count or hashlib.sha256(encoded).hexdigest()!=self.sha256: raise ValueError("text evidence does not match byte count or SHA-256")
    def canonical(self): return {"path":self.path,"kind":self.kind.value,"sha256":self.sha256,"byte_count":self.byte_count,"text_available":self.content is not None}

@dataclass(frozen=True)
class ProjectEvidenceBundle:
    manifest: RepositoryManifest; artifacts: tuple[EvidenceArtifact,...]; bundle_id: str=field(init=False); total_bytes: int=field(init=False)
    def __post_init__(self):
        if not isinstance(self.manifest,RepositoryManifest): raise TypeError("manifest must be a RepositoryManifest")
        if any(not isinstance(i,EvidenceArtifact) for i in self.artifacts): raise TypeError("artifacts must be EvidenceArtifact values")
        artifacts=tuple(sorted(self.artifacts,key=lambda x:x.path)); paths=tuple(i.path for i in artifacts); expected=tuple(e.path for e in self.manifest.entries)
        if paths!=expected: raise ValueError("evidence artifacts must exactly match the complete manifest")
        expected_hashes={e.path:e.sha256 for e in self.manifest.entries}
        if any(i.sha256!=expected_hashes[i.path] for i in artifacts): raise ValueError("evidence artifact does not match its manifest SHA-256")
        object.__setattr__(self,"artifacts",artifacts); object.__setattr__(self,"total_bytes",sum(i.byte_count for i in artifacts)); object.__setattr__(self,"bundle_id",_canonical_digest({"manifest_id":self.manifest.manifest_id,"artifacts":[i.canonical() for i in artifacts]}))

@dataclass(frozen=True)
class AuditFindingCandidate:
    key: str; title: str; classification: FindingClassification; severity: FindingSeverity; summary: str; rationale: str; evidence: tuple[object,...]=(); counterevidence: tuple[object,...]=(); consequences: tuple[str,...]=()
    def __post_init__(self):
        _validate_non_empty(self.key,"finding key"); _validate_non_empty(self.title,"finding title"); _validate_non_empty(self.summary,"finding summary"); _validate_non_empty(self.rationale,"finding rationale")
    def canonical(self): return {"key":self.key,"title":self.title,"classification":self.classification.value,"severity":self.severity.value,"summary":self.summary,"rationale":self.rationale,"consequences":list(self.consequences)}

@dataclass(frozen=True)
class MaturityAssessment:
    level:MaturityLevel; status:MaturityStatus; rationale:str; finding_keys:tuple[str,...]
    def __post_init__(self): _validate_non_empty(self.rationale,"maturity rationale"); object.__setattr__(self,"finding_keys",tuple(sorted(self.finding_keys)))
    def canonical(self): return {"level":self.level.value,"status":self.status.value,"rationale":self.rationale,"finding_keys":list(self.finding_keys)}

@dataclass(frozen=True)
class ProjectAuditCandidate:
    findings:tuple[AuditFindingCandidate,...]; maturity:tuple[MaturityAssessment,...]; recommendation:AuditRecommendation
    def __post_init__(self):
        if not self.findings: raise ValueError("audit candidate must contain findings")
        object.__setattr__(self,"findings",tuple(sorted(self.findings,key=lambda x:x.key))); object.__setattr__(self,"maturity",tuple(sorted(self.maturity,key=lambda x:x.level.value)))

@dataclass(frozen=True)
class ProjectAuditRequest:
    agent_identity:str; agent_role:str; resource:str; context_packet:ContextPacket; evidence_bundle:ProjectEvidenceBundle; objectives:tuple[str,...]; target_maturity:MaturityLevel=MaturityLevel.PRODUCTION_READY
    def __post_init__(self):
        for name in ("agent_identity","agent_role","resource"): _validate_non_empty(getattr(self,name),name)
        if not isinstance(self.context_packet,ContextPacket): raise TypeError("context_packet must be a ContextPacket")
        if self.context_packet.agent_identity!=self.agent_identity: raise ValueError("context packet agent identity does not match the audit request")
        if self.context_packet.purpose!=PROJECT_AUDIT_ACTION: raise ValueError(f"context packet purpose must be {PROJECT_AUDIT_ACTION!r}")
        if self.resource!=self.evidence_bundle.manifest.repository: raise ValueError("audit resource must match the evidence repository")
        objectives=tuple(self.objectives)
        if not objectives or any(not isinstance(i,str) or not i.strip() for i in objectives) or len(objectives)!=len(set(objectives)): raise ValueError("objectives must be non-empty unique strings")
        object.__setattr__(self,"objectives",tuple(sorted(objectives)))
    @property
    def context_packet_id(self): return self.context_packet.packet_id
    @property
    def objectives_fingerprint(self): return _canonical_digest(list(self.objectives))
    @property
<<<<<<< HEAD
    def request_fingerprint(self) -> str:
        return _canonical_digest(
            {
                "action": PROJECT_AUDIT_ACTION,
                "agent_identity": self.agent_identity,
                "agent_role": self.agent_role,
                "resource": self.resource,
                "context_packet_id": self.context_packet_id,
                "evidence_bundle_id": self.evidence_bundle.bundle_id,
                "objectives": list(self.objectives),
                "target_maturity": self.target_maturity.value,
            }
        )

    def authority_context(self) -> Mapping[str, str]:
        return {
            "audit_request_fingerprint": self.request_fingerprint,
            "evidence_bundle_id": self.evidence_bundle.bundle_id,
            "manifest_id": self.evidence_bundle.manifest.manifest_id,
            "objectives_fingerprint": self.objectives_fingerprint,
            "target_maturity": self.target_maturity.value,
        }

    def authority_request(self) -> AuthorityRequest:
        """Build the exact AI-3 question without granting authority."""
        return AuthorityRequest.create(
            request_id=self.request_fingerprint,
            agent_identity=self.agent_identity,
            agent_role=self.agent_role,
            action=PROJECT_AUDIT_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            context=self.authority_context(),
            parameters=self.execution_parameters(),
        )

    def execution_parameters(self) -> Mapping[str, str]:
        return {"audit_request_fingerprint": self.request_fingerprint}

    def execution_request(
        self, *, idempotency_key: str | None = None
    ) -> ExecutionRequest:
        authority_request = self.authority_request()
        return ExecutionRequest.create(
            request_id=authority_request.request_id,
            agent_identity=self.agent_identity,
            action=PROJECT_AUDIT_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            parameters=self.execution_parameters(),
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True)
class AuditFinding:
    """Evidence-validated, content-addressed advisory finding."""

    candidate: AuditFindingCandidate
    finding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, AuditFindingCandidate):
            raise TypeError("candidate must be an AuditFindingCandidate")
        object.__setattr__(
            self, "finding_id", _canonical_digest(self.candidate.canonical())
        )

    @property
    def key(self) -> str:
        return self.candidate.key

    @property
    def classification(self) -> FindingClassification:
        return self.candidate.classification

    @property
    def severity(self) -> FindingSeverity:
        return self.candidate.severity


@dataclass(frozen=True)
class ProjectAuditReport:
    """Validated advisory output; deliberately not a verification decision."""

    request: ProjectAuditRequest
    provider_id: str
    candidate: ProjectAuditCandidate
    findings: tuple[AuditFinding, ...] = field(init=False)
    report_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProjectAuditRequest):
            raise TypeError("request must be a ProjectAuditRequest")
        _validate_non_empty(self.provider_id, "provider_id")
        if not isinstance(self.candidate, ProjectAuditCandidate):
            raise TypeError("candidate must be a ProjectAuditCandidate")

        for finding in self.candidate.findings:
            for assertion in finding.evidence + finding.counterevidence:
                if not _assertion_holds(self.request.evidence_bundle, assertion):
                    raise InvalidProjectAuditReportError(
                        f"finding {finding.key!r} has unsupported evidence: "
                        f"{assertion.predicate.value} {assertion.path}"
                    )

        keys = {finding.key for finding in self.candidate.findings}
        for assessment in self.candidate.maturity:
            unknown = set(assessment.finding_keys) - keys
            if unknown:
                raise InvalidProjectAuditReportError(
                    "maturity assessment references unknown findings: "
                    + ", ".join(sorted(unknown))
                )

        minimum = _minimum_recommendation(self.candidate)
        if _recommendation_rank(self.candidate.recommendation) < _recommendation_rank(
            minimum
        ):
            raise InvalidProjectAuditReportError(
                f"recommendation understates validated evidence; minimum is {minimum.value}"
            )

        findings = tuple(AuditFinding(item) for item in self.candidate.findings)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(
            self,
            "report_id",
            _canonical_digest(
                {
                    "request_fingerprint": self.request.request_fingerprint,
                    "provider_id": self.provider_id,
                    "finding_ids": [item.finding_id for item in findings],
                    "maturity": [item.canonical() for item in self.candidate.maturity],
                    "recommendation": self.candidate.recommendation.value,
                }
            ),
        )

    @property
    def request_fingerprint(self) -> str:
        return self.request.request_fingerprint

    @property
    def recommendation(self) -> AuditRecommendation:
        return self.candidate.recommendation

    @property
    def authoritative(self) -> bool:
        return False


def _assertion_holds(
    bundle: ProjectEvidenceBundle, assertion: EvidenceAssertion
) -> bool:
    artifact = bundle.artifact(assertion.path)
    if assertion.predicate is EvidencePredicate.PATH_EXISTS:
        return artifact is not None
    if assertion.predicate is EvidencePredicate.PATH_ABSENT:
        return artifact is None
    if artifact is None:
        return False
    if assertion.predicate is EvidencePredicate.SHA256_EQUALS:
        return artifact.sha256 == assertion.expected
    if artifact.content is None:
        return False
    if assertion.predicate is EvidencePredicate.TEXT_CONTAINS:
        return (assertion.expected or "") in artifact.content
    if assertion.predicate is EvidencePredicate.TEXT_ABSENT:
        return (assertion.expected or "") not in artifact.content
    return False


def _assertion_sort_key(assertion: EvidenceAssertion) -> tuple[str, str, str]:
    return (assertion.path, assertion.predicate.value, assertion.expected or "")


def _minimum_recommendation(candidate: ProjectAuditCandidate) -> AuditRecommendation:
    facts = tuple(
        finding
        for finding in candidate.findings
        if finding.classification is FindingClassification.FACT
    )
    if any(finding.severity is FindingSeverity.CRITICAL for finding in facts):
        return AuditRecommendation.ESCALATE
    if any(finding.severity is FindingSeverity.HIGH for finding in facts):
        return AuditRecommendation.REPLAN
    if any(
        finding.severity in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}
        for finding in candidate.findings
    ):
        return AuditRecommendation.REPLAN
    if any(item.status is not MaturityStatus.ACHIEVED for item in candidate.maturity):
        return AuditRecommendation.CONTINUE_WITH_GAPS
    if any(
        finding.severity
        in {FindingSeverity.MEDIUM, FindingSeverity.HIGH, FindingSeverity.CRITICAL}
        for finding in candidate.findings
    ):
        return AuditRecommendation.CONTINUE_WITH_GAPS
    return AuditRecommendation.CONTINUE


def _maturity_rank(level: MaturityLevel) -> int:
    return tuple(MaturityLevel).index(level)


def _recommendation_rank(recommendation: AuditRecommendation) -> int:
    return tuple(AuditRecommendation).index(recommendation)
=======
    def request_fingerprint(self): return _canonical_digest({"action":PROJECT_AUDIT_ACTION,"agent_identity":self.agent_identity,"agent_role":self.agent_role,"resource":self.resource,"context_packet_id":self.context_packet_id,"evidence_bundle_id":self.evidence_bundle.bundle_id,"objectives":list(self.objectives),"target_maturity":self.target_maturity.value})
    def authority_context(self): return {"audit_request_fingerprint":self.request_fingerprint,"evidence_bundle_id":self.evidence_bundle.bundle_id,"manifest_id":self.evidence_bundle.manifest.manifest_id,"objectives_fingerprint":self.objectives_fingerprint,"target_maturity":self.target_maturity.value}
    def execution_parameters(self): return {"audit_request_fingerprint":self.request_fingerprint}
    def authority_request(self): return AuthorityRequest.create(agent_identity=self.agent_identity,agent_role=self.agent_role,action=PROJECT_AUDIT_ACTION,resource=self.resource,context_packet_id=self.context_packet_id,context=self.authority_context(),parameters=self.execution_parameters())
    def execution_request(self, authority_request: AuthorityRequest, *, idempotency_key: str|None=None):
        return ExecutionRequest.create(request_id=authority_request.request_id,agent_identity=authority_request.agent_identity,action=authority_request.action,resource=authority_request.resource,context_packet_id=authority_request.context_packet_id,parameters=authority_request.parameters,idempotency_key=idempotency_key)
>>>>>>> origin/phase4/p4-08-02-safe-patch-apply-v3
