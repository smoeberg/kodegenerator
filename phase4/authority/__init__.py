"""Phase 4 AI-3 Authority Engine public contract."""

from .adapter import CouncilDecisionAdapter, DecisionReadiness, RiskLevel
from .audit import (
    AuthorityAuditSink,
    NullAuthorityAuditSink,
    RecordingAuthorityAuditSink,
    composite_audit_sink,
)
from .engine import AuthorityEngine, AuthorityError, PolicyValidationError
from .grants import DEFAULT_GRANT_TTL_SECONDS, VerifiedAuthorityGrant
from .models import (
    AuthorityDecision,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)

__all__ = [
    "AuthorityDecision",
    "AuthorityPolicy",
    "AuthorityRequest",
    "AuthorityRule",
    "Decision",
    "VerifiedAuthorityGrant",
    "DEFAULT_GRANT_TTL_SECONDS",
    "AuthorityEngine",
    "AuthorityError",
    "PolicyValidationError",
    "AuthorityAuditSink",
    "NullAuthorityAuditSink",
    "RecordingAuthorityAuditSink",
    "composite_audit_sink",
    "CouncilDecisionAdapter",
    "DecisionReadiness",
    "RiskLevel",
]

__version__ = "4.0.1"
