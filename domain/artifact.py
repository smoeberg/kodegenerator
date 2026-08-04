# domain/artifact.py
"""
Artifact Domain Model

Represents a verifiable organizational output with versioning, provenance, and governance.
Artifacts are first-class primitives in DOR and serve as the tangible outputs of execution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime
from enum import Enum, auto
import hashlib
import uuid

if TYPE_CHECKING:
    from domain.actor import Actor
    from domain.organization import Organization
    from domain.workflow import Workflow


class ArtifactType(Enum):
    """Types of Artifacts."""
    SPECIFICATION = auto()
    ARCHITECTURE = auto()
    IMPLEMENTATION = auto()
    REVIEW = auto()
    DECISION = auto()
    RELEASE = auto()
    LEGAL = auto()
    FINANCIAL = auto()
    DOCUMENTATION = auto()
    CONFIGURATION = auto()
    DATA = auto()
    MODEL = auto()
    MANIFEST = auto()


class ArtifactState(Enum):
    """States of an Artifact."""
    DRAFT = auto()
    SUBMITTED = auto()
    IN_REVIEW = auto()
    APPROVED = auto()
    REJECTED = auto()
    RELEASED = auto()
    ARCHIVED = auto()


class GovernanceState(Enum):
    """Governance state of an Artifact."""
    DRAFT = auto()
    SUBMITTED = auto()
    IN_REVIEW = auto()
    APPROVED = auto()
    REJECTED = auto()
    EXEMPT = auto()


@dataclass
class Signature:
    """Represents a signature (approval/rejection) on an Artifact."""
    role_id: str
    actor_id: str
    status: str
    comments: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    evidence: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_id": self.role_id,
            "actor_id": self.actor_id,
            "status": self.status,
            "comments": self.comments,
            "timestamp": self.timestamp.isoformat(),
            "evidence": self.evidence
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Signature":
        return cls(
            role_id=data["role_id"],
            actor_id=data["actor_id"],
            status=data["status"],
            comments=data.get("comments", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.utcnow(),
            evidence=data.get("evidence")
        )


@dataclass
class Provenance:
    """Represents the provenance (origin) of an Artifact."""
    intent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    execution_id: Optional[str] = None
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    prompt: Optional[str] = None
    input_artifacts: List[str] = field(default_factory=list)
    parent_artifacts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt": self.prompt,
            "input_artifacts": self.input_artifacts,
            "parent_artifacts": self.parent_artifacts
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Provenance":
        return cls(
            intent_id=data.get("intent_id"),
            workflow_id=data.get("workflow_id"),
            task_id=data.get("task_id"),
            execution_id=data.get("execution_id"),
            model_id=data.get("model_id"),
            model_version=data.get("model_version"),
            prompt=data.get("prompt"),
            input_artifacts=data.get("input_artifacts", []),
            parent_artifacts=data.get("parent_artifacts", [])
        )


@dataclass
class Artifact:
    """Represents a verifiable organizational output with versioning, provenance, and governance."""
    id: str
    artifact_id: str = field(default_factory=lambda: f"artifact_{uuid.uuid4().hex[:8]}")
    version: str = "1.0.0"
    artifact_type: ArtifactType = ArtifactType.IMPLEMENTATION
    content_digest: str = ""
    content: Optional[str] = None
    content_location: Optional[str] = None
    content_type: str = "text/plain"
    
    organization_id: Optional[str] = None
    owner: Optional["Actor"] = None
    
    state: ArtifactState = ArtifactState.DRAFT
    governance_state: GovernanceState = GovernanceState.DRAFT
    
    provenance: Provenance = field(default_factory=Provenance)
    signatures: List[Signature] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)
    children: List[str] = field(default_factory=list)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not hasattr(self, 'id') or self.id is None:
            object.__setattr__(self, 'id', str(uuid.uuid4()))
        if self.content and not self.content_digest:
            self.content_digest = self.calculate_hash(self.content)

    def calculate_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_content(self, content: str) -> bool:
        return self.calculate_hash(content) == self.content_digest

    def add_signature(self, signature: Signature) -> None:
        self.signatures.append(signature)
        self.updated_at = datetime.utcnow()

    def is_approved(self) -> bool:
        if not self.signatures:
            return False
        return all(sig.status == "approved" for sig in self.signatures)

    def get_consensus_score(self) -> float:
        if not self.signatures:
            return 0.0
        approved = sum(1 for sig in self.signatures if sig.status == "approved")
        return (approved / len(self.signatures)) * 100

    def add_parent(self, parent_id: str) -> None:
        if parent_id not in self.parents:
            self.parents.append(parent_id)
            self.updated_at = datetime.utcnow()

    def add_child(self, child_id: str) -> None:
        if child_id not in self.children:
            self.children.append(child_id)
            self.updated_at = datetime.utcnow()

    def submit_for_review(self) -> None:
        if self.state == ArtifactState.DRAFT:
            self.state = ArtifactState.SUBMITTED
            self.governance_state = GovernanceState.SUBMITTED
            self.updated_at = datetime.utcnow()

    def approve(self, role_id: str, actor_id: str, comments: str = "") -> None:
        self.add_signature(Signature(role_id=role_id, actor_id=actor_id, status="approved", comments=comments))
        if self.is_approved():
            self.state = ArtifactState.APPROVED
            self.governance_state = GovernanceState.APPROVED
        else:
            self.state = ArtifactState.IN_REVIEW
            self.governance_state = GovernanceState.IN_REVIEW
        self.updated_at = datetime.utcnow()

    def reject(self, role_id: str, actor_id: str, comments: str = "") -> None:
        self.add_signature(Signature(role_id=role_id, actor_id=actor_id, status="rejected", comments=comments))
        self.state = ArtifactState.REJECTED
        self.governance_state = GovernanceState.REJECTED
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "version": self.version,
            "artifact_type": self.artifact_type.name,
            "content_digest": self.content_digest,
            "content_type": self.content_type,
            "organization_id": self.organization_id,
            "owner_id": self.owner.id if self.owner else None,
            "state": self.state.name,
            "governance_state": self.governance_state.name,
            "provenance": self.provenance.to_dict(),
            "signatures": [s.to_dict() for s in self.signatures],
            "parents": self.parents,
            "children": self.children,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "Artifact":
        provenance = Provenance.from_dict(data.get("provenance", {}))
        signatures = [Signature.from_dict(s) for s in data.get("signatures", [])]
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            artifact_id=data.get("artifact_id", f"artifact_{uuid.uuid4().hex[:8]}"),
            version=data.get("version", "1.0.0"),
            artifact_type=ArtifactType[data.get("artifact_type", "IMPLEMENTATION")],
            content_digest=data.get("content_digest", ""),
            content=data.get("content"),
            content_location=data.get("content_location"),
            content_type=data.get("content_type", "text/plain"),
            organization_id=data.get("organization_id"),
            state=ArtifactState[data.get("state", "DRAFT")],
            governance_state=GovernanceState[data.get("governance_state", "DRAFT")],
            provenance=provenance,
            signatures=signatures,
            parents=data.get("parents", []),
            children=data.get("children", []),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            **kwargs
        )
