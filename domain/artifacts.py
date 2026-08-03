# domain/artifacts.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .artifact import Artifact, ArtifactType, ArtifactState

@dataclass
class ArchitectureArtifact(Artifact):
    """Arkitektur-artefakt (f.eks. ADR, Interface Definition)."""
    artifact_type: ArtifactType = ArtifactType.ARCHITECTURE
    adrs: List[Dict] = field(default_factory=list)  # Liste af ADR'er
    interfaces: List[Dict] = field(default_factory=list)  # Liste af interfaces
    contracts: List[Dict] = field(default_factory=list)  # Liste af kontrakter

@dataclass
class ImplementationArtifact(Artifact):
    """Implementerings-artefakt (f.eks. Kode, Tests)."""
    artifact_type: ArtifactType = ArtifactType.IMPLEMENTATION
    code: Dict[str, str] = field(default_factory=dict)  # Filnavn → indhold
    tests: Dict[str, str] = field(default_factory=dict)  # Filnavn → indhold
    test_coverage: float = 0.0  # Testdækning (0-1)
    dependencies: List[str] = field(default_factory=list)  # Afhængigheder (artefakt-ID'er)

@dataclass
class ReviewArtifact(Artifact):
    """Review-artefakt (f.eks. Code Review, Security Review)."""
    artifact_type: ArtifactType = ArtifactType.REVIEW
    reviews: List[Dict] = field(default_factory=list)  # Liste af reviews
    consensus_score: float = 0.0  # Konsensus-score (0-100)
    decision: str = "pending"  # "approve", "reject", "needs_changes"
    conditions: List[str] = field(default_factory=list)  # Betingelser for godkendelse
