"""Immutable contracts for the Phase 4B-2 Project Audit Agent."""
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
PROJECT_AUDIT_SYSTEM_ORGANIZATION = "system:project-audit"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")

class ProjectAuditContractError(ValueError): pass
class InvalidProjectAuditReportError(ProjectAuditContractError): pass


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def _validate_non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProjectAuditContractError(f"{name} must be a non-empty string without outer whitespace")
    return value

def _validate_repository_path(path: str) -> str:
    _validate_non_empty(path, "repository path")
    p = PurePosixPath(path)
    if "\\" in path or p.is_absolute() or path.startswith("/") or not p.parts or any(x in {"", ".", ".."} for x in p.parts) or p.as_posix() != path:
        raise ProjectAuditContractError("repository paths must be canonical POSIX paths")
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
        if not isinstance(self.sha256,str) or not _HEX_DIGEST.fullmatch(self.sha256): raise ProjectAuditContractError("manifest SHA-256 must be 64 lowercase hex")
    def canonical(self): return {"path":self.path,"sha256":self.sha256}

@dataclass(frozen=True)
class RepositoryManifest:
    repository: str; commit_sha: str; entries: tuple[ManifestEntry,...]; complete: bool=True; manifest_id: str=field(init=False)
    def __post_init__(self):
        _validate_non_empty(self.repository,"repository")
        if not isinstance(self.commit_sha,str) or not _REVISION.fullmatch(self.commit_sha): raise ProjectAuditContractError("commit_sha must be 7-64 lowercase hexadecimal characters")
        if type(self.complete) is not bool or not self.complete: raise ProjectAuditContractError("whole-project audit requires a complete tracked-file manifest")
        entries=tuple(sorted(self.entries,key=lambda x:x.path))
        if not entries or any(not isinstance(x,ManifestEntry) for x in entries): raise ProjectAuditContractError("manifest entries must be non-empty ManifestEntry values")
        if len({x.path for x in entries}) != len(entries): raise ProjectAuditContractError("manifest paths must be unique")
        object.__setattr__(self,"entries",entries); object.__setattr__(self,"manifest_id",_canonical_digest({"repository":self.repository,"commit_sha":self.commit_sha,"complete":self.complete,"entries":[x.canonical() for x in entries]}))

@dataclass(frozen=True, order=True)
class EvidenceArtifact:
    path: str; kind: EvidenceKind; sha256: str; byte_count: int; content: str|None=None
    def __post_init__(self):
        object.__setattr__(self,"path",_validate_repository_path(self.path))
        if not isinstance(self.kind,EvidenceKind): raise TypeError("kind must be an EvidenceKind")
        if not isinstance(self.sha256,str) or not _HEX_DIGEST.fullmatch(self.sha256): raise ProjectAuditContractError("artifact SHA-256 must be 64 lowercase hex")
        if type(self.byte_count) is not int or self.byte_count<0: raise ProjectAuditContractError("byte_count must be non-negative")
        if self.content is not None:
            encoded=self.content.encode();
            if len(encoded)!=self.byte_count or hashlib.sha256(encoded).hexdigest()!=self.sha256: raise ProjectAuditContractError("text evidence does not match byte count or SHA-256")
    def canonical(self): return {"path":self.path,"kind":self.kind.value,"sha256":self.sha256,"byte_count":self.byte_count,"text_available":self.content is not None}

@dataclass(frozen=True)
class ProjectEvidenceBundle:
    manifest: RepositoryManifest; artifacts: tuple[EvidenceArtifact,...]; bundle_id: str=field(init=False); total_bytes:int=field(init=False)
    def __post_init__(self):
        artifacts=tuple(sorted(self.artifacts,key=lambda x:x.path)); expected=tuple(x.path for x in self.manifest.entries)
        if tuple(x.path for x in artifacts)!=expected: raise ProjectAuditContractError("evidence artifacts must exactly match the complete manifest")
        hashes={x.path:x.sha256 for x in self.manifest.entries}
        if any(x.sha256!=hashes[x.path] for x in artifacts): raise ProjectAuditContractError("evidence artifact does not match its manifest SHA-256")
        object.__setattr__(self,"artifacts",artifacts); object.__setattr__(self,"total_bytes",sum(x.byte_count for x in artifacts)); object.__setattr__(self,"bundle_id",_canonical_digest({"manifest_id":self.manifest.manifest_id,"artifacts":[x.canonical() for x in artifacts]}))
    @property
    def repository(self): return self.manifest.repository
    @property
    def commit_sha(self): return self.manifest.commit_sha
    def artifact(self,path):
        return next((x for x in self.artifacts if x.path==_validate_repository_path(path)),None)

@dataclass(frozen=True)
class EvidenceAssertion:
    path: str; predicate: EvidencePredicate; expected: str|None=None
    def __post_init__(self):
        object.__setattr__(self,"path",_validate_repository_path(self.path))
        if self.predicate in {EvidencePredicate.PATH_EXISTS,EvidencePredicate.PATH_ABSENT} and self.expected is not None: raise ProjectAuditContractError("path predicates do not accept an expected value")
        if self.predicate not in {EvidencePredicate.PATH_EXISTS,EvidencePredicate.PATH_ABSENT} and not isinstance(self.expected,str): raise ProjectAuditContractError("text and digest predicates require an expected value")
        if self.predicate is EvidencePredicate.SHA256_EQUALS and not _HEX_DIGEST.fullmatch(self.expected or ""): raise ProjectAuditContractError("SHA256_EQUALS requires a 64-character lowercase digest")
    def canonical(self): return {"path":self.path,"predicate":self.predicate.value,"expected":self.expected}

@dataclass(frozen=True)
class AuditFindingCandidate:
    key:str; title:str; classification:FindingClassification; severity:FindingSeverity; summary:str; rationale:str; evidence:tuple[EvidenceAssertion,...]; counterevidence:tuple[EvidenceAssertion,...]=(); consequences:tuple[str,...]=()
    def __post_init__(self):
        for n in ("key","title","summary","rationale"): _validate_non_empty(getattr(self,n),n)
        if not isinstance(self.classification,FindingClassification) or not isinstance(self.severity,FindingSeverity): raise TypeError("invalid finding classification or severity")
        if not self.evidence and not self.counterevidence: raise ProjectAuditContractError("every finding requires evidence or counterevidence")
        assertions=self.evidence+self.counterevidence
        if any(not isinstance(x,EvidenceAssertion) for x in assertions) or len(assertions)!=len(set(assertions)): raise ProjectAuditContractError("finding evidence assertions must be unique EvidenceAssertion values")
        object.__setattr__(self,"evidence",tuple(sorted(self.evidence,key=_assertion_sort_key))); object.__setattr__(self,"counterevidence",tuple(sorted(self.counterevidence,key=_assertion_sort_key)))
    def canonical(self): return {"key":self.key,"title":self.title,"classification":self.classification.value,"severity":self.severity.value,"summary":self.summary,"rationale":self.rationale,"evidence":[x.canonical() for x in self.evidence],"counterevidence":[x.canonical() for x in self.counterevidence],"consequences":list(self.consequences)}

@dataclass(frozen=True)
class MaturityAssessment:
    level:MaturityLevel; status:MaturityStatus; rationale:str; finding_keys:tuple[str,...]
    def __post_init__(self):
        if not isinstance(self.level,MaturityLevel) or not isinstance(self.status,MaturityStatus): raise TypeError("invalid maturity value")
        _validate_non_empty(self.rationale,"maturity rationale")
        if not self.finding_keys: raise ProjectAuditContractError("each maturity assessment must reference at least one finding")
        object.__setattr__(self,"finding_keys",tuple(sorted(self.finding_keys)))
    def canonical(self): return {"level":self.level.value,"status":self.status.value,"rationale":self.rationale,"finding_keys":list(self.finding_keys)}

@dataclass(frozen=True)
class ProjectAuditCandidate:
    findings:tuple[AuditFindingCandidate,...]; maturity:tuple[MaturityAssessment,...]; recommendation:AuditRecommendation
    def __post_init__(self):
        if not self.findings: raise ProjectAuditContractError("audit candidate must contain findings")
        if len({x.key for x in self.findings})!=len(self.findings): raise ProjectAuditContractError("audit finding keys must be unique")
        if set(x.level for x in self.maturity)!=set(MaturityLevel): raise ProjectAuditContractError("audit candidate must assess every maturity level exactly once")
        object.__setattr__(self,"findings",tuple(sorted(self.findings,key=lambda x:x.key))); object.__setattr__(self,"maturity",tuple(sorted(self.maturity,key=lambda x:x.level.value)))

@dataclass(frozen=True)
class ProjectAuditRequest:
    agent_identity:str; agent_role:str; resource:str; context_packet:ContextPacket; evidence_bundle:ProjectEvidenceBundle; objectives:tuple[str,...]; target_maturity:MaturityLevel=MaturityLevel.PRODUCTION_READY; organization_id:str=PROJECT_AUDIT_SYSTEM_ORGANIZATION
    def __post_init__(self):
        for n in ("agent_identity","agent_role","resource","organization_id"): _validate_non_empty(getattr(self,n),n)
        if not isinstance(self.context_packet,ContextPacket): raise TypeError("context_packet must be a ContextPacket")
        if self.context_packet.agent_identity!=self.agent_identity: raise ProjectAuditContractError("context packet agent identity does not match the audit request")
        if self.context_packet.purpose!=PROJECT_AUDIT_ACTION: raise ProjectAuditContractError(f"context packet purpose must be {PROJECT_AUDIT_ACTION!r}")
        if self.resource!=self.evidence_bundle.repository: raise ProjectAuditContractError("audit resource must match the evidence repository")
        objectives=tuple(self.objectives)
        if not objectives or len(objectives)!=len(set(objectives)) or any(not isinstance(x,str) or not x.strip() for x in objectives): raise ProjectAuditContractError("objectives must be non-empty unique strings")
        object.__setattr__(self,"objectives",tuple(sorted(objectives)))
    @property
    def context_packet_id(self): return self.context_packet.packet_id
    @property
    def objectives_fingerprint(self): return _canonical_digest(list(self.objectives))
    @property
    def request_fingerprint(self): return _canonical_digest({"action":PROJECT_AUDIT_ACTION,"agent_identity":self.agent_identity,"agent_role":self.agent_role,"resource":self.resource,"organization_id":self.organization_id,"context_packet_id":self.context_packet_id,"evidence_bundle_id":self.evidence_bundle.bundle_id,"objectives":list(self.objectives),"target_maturity":self.target_maturity.value})
    def authority_context(self)->Mapping[str,str]: return {"audit_request_fingerprint":self.request_fingerprint,"evidence_bundle_id":self.evidence_bundle.bundle_id,"manifest_id":self.evidence_bundle.manifest.manifest_id,"objectives_fingerprint":self.objectives_fingerprint,"target_maturity":self.target_maturity.value,"organization_id":self.organization_id}
    def execution_parameters(self)->Mapping[str,str]: return {"audit_request_fingerprint":self.request_fingerprint}
    def authority_request(self)->AuthorityRequest: return AuthorityRequest.create(request_id=self.request_fingerprint,agent_identity=self.agent_identity,agent_role=self.agent_role,action=PROJECT_AUDIT_ACTION,resource=self.resource,context_packet_id=self.context_packet_id,context=self.authority_context(),parameters=self.execution_parameters(),organization_id=self.organization_id)
    def execution_request(self, *, idempotency_key:str|None=None)->ExecutionRequest:
        return ExecutionRequest.create(request_id=self.request_fingerprint,agent_identity=self.agent_identity,action=PROJECT_AUDIT_ACTION,resource=self.resource,context_packet_id=self.context_packet_id,organization_id=self.organization_id,parameters=self.execution_parameters(),idempotency_key=idempotency_key)

@dataclass(frozen=True)
class AuditFinding:
    candidate:AuditFindingCandidate; finding_id:str=field(init=False)
    def __post_init__(self): object.__setattr__(self,"finding_id",_canonical_digest(self.candidate.canonical()))
    @property
    def key(self): return self.candidate.key
    @property
    def classification(self): return self.candidate.classification
    @property
    def severity(self): return self.candidate.severity
    def canonical(self): return self.candidate.canonical()

@dataclass(frozen=True)
class ProjectAuditReport:
    request:ProjectAuditRequest; provider_id:str; candidate:ProjectAuditCandidate; findings:tuple[AuditFinding,...]=field(init=False); report_id:str=field(init=False)
    def __post_init__(self):
        _validate_non_empty(self.provider_id,"provider_id")
        for finding in self.candidate.findings:
            for assertion in finding.evidence+finding.counterevidence:
                if not _assertion_holds(self.request.evidence_bundle,assertion): raise InvalidProjectAuditReportError(f"finding {finding.key!r} has unsupported evidence: {assertion.predicate.value} {assertion.path}")
        keys={x.key for x in self.candidate.findings}
        for assessment in self.candidate.maturity:
            if set(assessment.finding_keys)-keys: raise InvalidProjectAuditReportError("maturity assessment references unknown findings: "+", ".join(sorted(set(assessment.finding_keys)-keys)))
        minimum=_minimum_recommendation(self.candidate)
        if _recommendation_rank(self.candidate.recommendation)<_recommendation_rank(minimum): raise InvalidProjectAuditReportError(f"recommendation understates validated evidence; minimum is {minimum.value}")
        findings=tuple(AuditFinding(x) for x in self.candidate.findings); object.__setattr__(self,"findings",findings); object.__setattr__(self,"report_id",_canonical_digest({"request_fingerprint":self.request.request_fingerprint,"provider_id":self.provider_id,"finding_ids":[x.finding_id for x in findings],"maturity":[x.canonical() for x in self.candidate.maturity],"recommendation":self.candidate.recommendation.value}))
    @property
    def request_fingerprint(self): return self.request.request_fingerprint
    @property
    def recommendation(self): return self.candidate.recommendation
    @property
    def authoritative(self): return False

def _assertion_holds(bundle, assertion):
    artifact=bundle.artifact(assertion.path)
    if assertion.predicate is EvidencePredicate.PATH_EXISTS: return artifact is not None
    if assertion.predicate is EvidencePredicate.PATH_ABSENT: return artifact is None
    if artifact is None: return False
    if assertion.predicate is EvidencePredicate.SHA256_EQUALS: return artifact.sha256==assertion.expected
    if artifact.content is None: return False
    if assertion.predicate is EvidencePredicate.TEXT_CONTAINS: return (assertion.expected or "") in artifact.content
    if assertion.predicate is EvidencePredicate.TEXT_ABSENT: return (assertion.expected or "") not in artifact.content
    return False

def _assertion_sort_key(a): return (a.path,a.predicate.value,a.expected or "")
def _minimum_recommendation(candidate):
    facts=[x for x in candidate.findings if x.classification is FindingClassification.FACT]
    if any(x.severity is FindingSeverity.CRITICAL for x in facts): return AuditRecommendation.ESCALATE
    if any(x.severity is FindingSeverity.HIGH for x in facts): return AuditRecommendation.REPLAN
    if any(x.status is not MaturityStatus.ACHIEVED for x in candidate.maturity): return AuditRecommendation.CONTINUE_WITH_GAPS
    if any(x.severity in {FindingSeverity.MEDIUM,FindingSeverity.HIGH,FindingSeverity.CRITICAL} for x in candidate.findings): return AuditRecommendation.CONTINUE_WITH_GAPS
    return AuditRecommendation.CONTINUE

def _recommendation_rank(x): return tuple(AuditRecommendation).index(x)
