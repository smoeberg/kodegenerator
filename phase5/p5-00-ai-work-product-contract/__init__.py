"""P5-00 AI Work Product Contract and Verification Protocol.

Agent completion claims are non-authoritative. Work products are accepted only
when the submitted artifact state satisfies its immutable contract through
independent verification.
"""

from .models import (
    AcceptanceCriterion,
    AIWorkProductContract,
    ArtifactRequirement,
    ArtifactType,
    CandidateEvidence,
    CriterionResult,
    EvidenceAuthority,
    RepositoryState,
    SubmittedArtifact,
    VerificationDecision,
    VerificationProcedure,
    WorkProductSubmission,
)
from .lifecycle import ActorRole, DeliveryState, LifecycleEvent, append_event, derive_delivery_state
from .fingerprinting import canonical_json, fingerprint
from .serialization import SCHEMA_VERSION, canonical_bytes, canonical_fingerprint
from .verification import GovernedFact, VerificationEngine, VerificationError

__all__ = [
    "AcceptanceCriterion", "AIWorkProductContract", "ArtifactRequirement", "ArtifactType",
    "CandidateEvidence", "CriterionResult", "EvidenceAuthority", "RepositoryState",
    "SubmittedArtifact", "VerificationDecision", "VerificationProcedure", "WorkProductSubmission",
    "ActorRole", "DeliveryState", "LifecycleEvent", "append_event", "derive_delivery_state",
    "canonical_json", "fingerprint", "SCHEMA_VERSION", "canonical_bytes", "canonical_fingerprint",
    "GovernedFact", "VerificationEngine", "VerificationError",
]
