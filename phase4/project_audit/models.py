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
    def request_fingerprint(self): return _canonical_digest({"action":PROJECT_AUDIT_ACTION,"agent_identity":self.agent_identity,"agent_role":self.agent_role,"resource":self.resource,"context_packet_id":self.context_packet_id,"evidence_bundle_id":self.evidence_bundle.bundle_id,"objectives":list(self.objectives),"target_maturity":self.target_maturity.value})
    def authority_context(self): return {"audit_request_fingerprint":self.request_fingerprint,"evidence_bundle_id":self.evidence_bundle.bundle_id,"manifest_id":self.evidence_bundle.manifest.manifest_id,"objectives_fingerprint":self.objectives_fingerprint,"target_maturity":self.target_maturity.value}
    def execution_parameters(self): return {"audit_request_fingerprint":self.request_fingerprint}
    def authority_request(self): return AuthorityRequest.create(agent_identity=self.agent_identity,agent_role=self.agent_role,action=PROJECT_AUDIT_ACTION,resource=self.resource,context_packet_id=self.context_packet_id,context=self.authority_context(),parameters=self.execution_parameters())
    def execution_request(self, authority_request: AuthorityRequest, *, idempotency_key: str|None=None):
        return ExecutionRequest.create(request_id=authority_request.request_id,agent_identity=authority_request.agent_identity,action=authority_request.action,resource=authority_request.resource,context_packet_id=authority_request.context_packet_id,parameters=authority_request.parameters,idempotency_key=idempotency_key)
