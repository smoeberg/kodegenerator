"""P5-00 AI Work Product Contract and Verification Protocol.

This package defines the contract/submission boundary for DOR work products.
Agent completion claims are non-authoritative; PASS/FAIL is reserved for the
independent verification authority.
"""

from .models import (
    AcceptanceCriterion,
    AIWorkProductContract,
    ArtifactRequirement,
    CandidateEvidence,
    CriterionResult,
    RepositoryState,
    SubmittedArtifact,
    VerificationDecision,
    VerificationProcedure,
    WorkProductSubmission,
)
from .lifecycle import (
    DeliveryState,
    LifecycleEvent,
    append_event,
    derive_delivery_state,
)
from .fingerprinting import canonical_json, fingerprint
from .verification import VerificationEngine, VerificationError

__all__ = [
    "AcceptanceCriterion",
    "AIWorkProductContract",
    "ArtifactRequirement",
    "CandidateEvidence",
    "CriterionResult",
    "RepositoryState",
    "SubmittedArtifact",
    "VerificationDecision",
    "VerificationProcedure",
    "WorkProductSubmission",
    "DeliveryState",
    "LifecycleEvent",
    "append_event",
    "derive_delivery_state",
    "canonical_json",
    "fingerprint",
    "VerificationEngine",
    "VerificationError",
]
