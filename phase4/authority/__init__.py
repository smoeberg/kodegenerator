"""Phase 4 AI-3 Authority Engine public contract."""

from .models import (
    AuthorityDecision,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from .grants import VerifiedAuthorityGrant
from .engine import AuthorityEngine, AuthorityError, PolicyValidationError

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
]

__version__ = "4.0.0"
