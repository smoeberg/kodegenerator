# domain/artifact.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto
import hashlib

class ArtifactState(Enum):
    """Tilstande for et Artifact."""
    DRAFT = auto()
    SUBMITTED = auto()
    IN_REVIEW = auto()
    APPROVED = auto()
    REJECTED = auto()
    RELEASED = auto()
    ARCHIVED = auto()

class ArtifactType(Enum):
    """Typer af Artifacts."""
    SPECIFICATION = auto()
    ARCHITECTURE = auto()
    IMPLEMENTATION = auto()
    REVIEW = auto()
    DECISION = auto()
    RELEASE = auto()
    LEGAL = auto()
    FINANCIAL = auto()

@dataclass
class Signature:
    """En signatur på et Artifact (godkendelse/afvisning)."""
    role_id: str
    actor_id: str
    status: str  # "approved", "rejected", "needs_changes"
    comments: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class Artifact:
    """Repræsenterer et verificerbart organisatorisk resultat."""
    id: str
    version: str  # f.eks. "1.0.0"
    artifact_type: ArtifactType
    hash: str  # SHA-256 hash af indholdet
    owner: Optional["Actor"] = None
    department_id: Optional[str] = None
    workflow_id: Optional[str] = None
    state: ArtifactState = ArtifactState.DRAFT
    signatures: List[Signature] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)  # Forældre-artefakter (IDs)
    children: List[str] = field(default_factory=list)  # Børn-artefakter (IDs)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Specifikke felter (udvides af subklasser)
    metadata: Dict = field(default_factory=dict)

    def calculate_hash(self, content: str) -> str:
        """Beregn SHA-256 hash af indholdet."""
        return hashlib.sha256(content.encode()).hexdigest()

    def add_signature(self, signature: Signature) -> None:
        """Tilføj en signatur til Artifact."""
        self.signatures.append(signature)

    def is_approved(self) -> bool:
        """Tjek om Artifact er godkendt."""
        return all(sig.status == "approved" for sig in self.signatures)

    def get_consensus_score(self) -> float:
        """Beregn konsensus-score (0-100) baseret på signaturer."""
        if not self.signatures:
            return 0.0
        approved = sum(1 for sig in self.signatures if sig.status == "approved")
        return (approved / len(self.signatures)) * 100

    def add_parent(self, parent_id: str) -> None:
        """Tilføj en forælder-artefakt."""
        if parent_id not in self.parents:
            self.parents.append(parent_id)

    def add_child(self, child_id: str) -> None:
        """Tilføj et barn-artefakt."""
        if child_id not in self.children:
            self.children.append(child_id)
