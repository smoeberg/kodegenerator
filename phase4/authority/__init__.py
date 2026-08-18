"""Phase 4 AI-3 Authority Engine public contract."""

from .audit import (
    AuthorityAuditSink,
    NullAuthorityAuditSink,
    RecordingAuthorityAuditSink,
    composite_audit_sink,
)
from .engine import AuthorityEngine, AuthorityError, PolicyValidationError
from .grants import VerifiedAuthorityGrant
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
    "AuthorityEngine",
    "AuthorityError",
    "PolicyValidationError",
    "AuthorityAuditSink",
    "NullAuthorityAuditSink",
    "RecordingAuthorityAuditSink",
    "composite_audit_sink",
]

__version__ = "4.0.1"
