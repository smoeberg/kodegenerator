"""Phase 3 authority domain contracts.

The canonical authority model is Actor -> RoleAssignment -> RoleDefinition
-> Capability. These objects are intentionally independent of persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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
    """Deterministic result of a runtime authorization evaluation."""

    allowed: bool
    reason: str
    reason_code: str = ""
    actor_id: str | None = None
    principal_id: str | None = None
    organization_id: str | None = None
    capability_id: str | None = None
    resource_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
