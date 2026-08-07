"""Phase 3 authority domain contracts.

The canonical authority model is Actor -> RoleAssignment -> RoleDefinition
-> Capability. These objects are intentionally independent of persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, ClassVar


@dataclass(frozen=True)
class Capability:
    """Atomic permission evaluated by the runtime."""

    id: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id or self.id.strip() != self.id:
            raise ValueError("Capability id must be a non-empty canonical string")
        if "." not in self.id:
            raise ValueError("Capability id must use dot-separated naming")


@dataclass(frozen=True)
class RoleDefinition:
    """Defines authority without identifying the actor holding it."""

    id: str
    name: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    status: str = "active"

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("RoleDefinition requires id and name")
        if self.status not in {"active", "inactive"}:
            raise ValueError("RoleDefinition status must be active or inactive")
        for capability in self.capabilities:
            Capability(capability)

    def grants(self, capability_id: str) -> bool:
        return self.status == "active" and capability_id in self.capabilities


@dataclass(frozen=True)
class RoleAssignment:
    """Organization-scoped assignment of a role to an actor."""

    actor_id: str
    organization_id: str
    role_definition_id: str
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.actor_id or not self.organization_id or not self.role_definition_id:
            raise ValueError("RoleAssignment requires actor, organization and role ids")
        if self.status not in {"active", "inactive", "revoked"}:
            raise ValueError("Invalid RoleAssignment status")


@dataclass(frozen=True)
class AuthorizationDecision:
    """Deterministic, self-validating result of authorization evaluation."""

    allowed: bool
    reason: str
    reason_code: str = ""
    actor_id: str | None = None
    principal_id: str | None = None
    organization_id: str | None = None
    capability_id: str | None = None
    resource_id: str | None = None
    resource_organization_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    CANONICAL_REASON_CODES: ClassVar[frozenset[str]] = frozenset(
        {
            "capability_granted",
            "capability_not_granted",
            "actor_not_in_organization",
            "actor_inactive",
            "resource_not_accessible",
            "command_organization_mismatch",
            "principal_actor_mismatch",
            "invalid_capability",
        }
    )

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("AuthorizationDecision requires a reason")
        if self.reason_code not in self.CANONICAL_REASON_CODES:
            raise ValueError("AuthorizationDecision reason_code is not canonical")
        if self.allowed != (self.reason_code == "capability_granted"):
            raise ValueError("AuthorizationDecision allowed flag conflicts with reason_code")
        if not self.actor_id or not self.principal_id or not self.organization_id:
            raise ValueError("AuthorizationDecision requires actor, principal and organization")
        if not self.capability_id:
            raise ValueError("AuthorizationDecision requires capability_id")
        if self.resource_id is not None and self.resource_organization_id is None:
            raise ValueError("Resource decisions require resource_organization_id")

    @property
    def fingerprint(self) -> str:
        """Return a deterministic integrity fingerprint for the decision itself."""
        canonical = {
            "allowed": self.allowed,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "actor_id": self.actor_id,
            "principal_id": self.principal_id,
            "organization_id": self.organization_id,
            "capability_id": self.capability_id,
            "resource_id": self.resource_id,
            "resource_organization_id": self.resource_organization_id,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
