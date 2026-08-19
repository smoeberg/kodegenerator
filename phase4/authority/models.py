"""Domain models for the Phase 4 AI-3 Authority Engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional, Tuple
import hashlib
import json


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class AuthorityRequest:
    """Immutable, canonical authorization request."""

    request_id: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    requested_at: str
    agent_role: Optional[str] = None
    context: Tuple[Tuple[str, str], ...] = ()
    parameters: Tuple[Tuple[str, str], ...] = ()
    organization_id: Optional[str] = None
    actor_id: Optional[str] = None
    capability: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("request_id", "agent_identity", "action", "resource", "context_packet_id", "requested_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.agent_role is not None and not self.agent_role.strip():
            raise ValueError("agent_role must be non-empty when supplied")
        for name in ("organization_id", "actor_id", "capability"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must be non-empty when supplied")
        for name, values in (("context", self.context), ("parameters", self.parameters)):
            keys = [key for key, _ in values]
            if len(keys) != len(set(keys)):
                raise ValueError(f"{name} keys must be unique")

    @staticmethod
    def create(
        agent_identity: str,
        action: str,
        resource: str,
        context_packet_id: str,
        *,
        agent_role: Optional[str] = None,
        context: Mapping[str, str] | None = None,
        parameters: Mapping[str, str] | None = None,
        request_id: str | None = None,
        organization_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> "AuthorityRequest":
        timestamp = datetime.now(timezone.utc).isoformat()
        canonical_context = tuple(sorted((str(k), str(v)) for k, v in (context or {}).items()))
        canonical_parameters = tuple(sorted((str(k), str(v)) for k, v in (parameters or {}).items()))
        identity_payload = {
            "agent_identity": agent_identity,
            "action": action,
            "resource": resource,
            "context_packet_id": context_packet_id,
            "agent_role": agent_role,
            "context": [list(item) for item in canonical_context],
            "parameters": [list(item) for item in canonical_parameters],
            "organization_id": organization_id,
            "actor_id": actor_id,
            "capability": capability,
        }
        encoded = json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
        canonical_request_id = hashlib.sha256(encoded).hexdigest()
        return AuthorityRequest(
            request_id=request_id or canonical_request_id,
            agent_identity=agent_identity,
            action=action,
            resource=resource,
            context_packet_id=context_packet_id,
            requested_at=timestamp,
            agent_role=agent_role,
            context=canonical_context,
            parameters=canonical_parameters,
            organization_id=organization_id,
            actor_id=actor_id,
            capability=capability,
        )


@dataclass(frozen=True)
class AuthorityRule:
    rule_id: str
    action: str
    resource_pattern: str
    effect: Decision
    agent_identity: Optional[str] = None
    agent_role: Optional[str] = None
    required_context: Tuple[Tuple[str, str], ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.action.strip() or not self.resource_pattern.strip():
            raise ValueError("rule_id, action and resource_pattern must be non-empty")
        if self.agent_identity is not None and not self.agent_identity.strip():
            raise ValueError("agent_identity must be non-empty when supplied")
        if self.agent_role is not None and not self.agent_role.strip():
            raise ValueError("agent_role must be non-empty when supplied")
        keys = [key for key, _ in self.required_context]
        if len(keys) != len(set(keys)):
            raise ValueError("required_context keys must be unique")


@dataclass(frozen=True)
class AuthorityPolicy:
    policy_id: str
    version: str
    rules: Tuple[AuthorityRule, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.version.strip():
            raise ValueError("policy_id and version must be non-empty")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule IDs must be unique")


@dataclass(frozen=True)
class AuthorityDecision:
    """Immutable authority result carrying exact request binding and provenance."""

    request_id: str
    decision: Decision
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    policy_id: str
    policy_version: str
    matched_rule_ids: Tuple[str, ...]
    reason: str
    evaluated_at: str
    parameters: Tuple[Tuple[str, str], ...] = ()
    organization_id: Optional[str] = None
    actor_id: Optional[str] = None
    capability: Optional[str] = None
    _provenance_token: object | None = field(default=None, init=False, repr=False, compare=False)
    _provenance_issuer: str = field(default="", init=False, repr=False, compare=False)
    _provenance_signature: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in ("request_id", "agent_identity", "action", "resource", "context_packet_id", "policy_id", "policy_version", "reason", "evaluated_at"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.decision, Decision):
            raise TypeError("decision must be a Decision")
        for name in ("organization_id", "actor_id", "capability"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must be non-empty when supplied")
        keys = [key for key, _ in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("parameter keys must be unique")

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def provenance_verified(self) -> bool:
        return self._provenance_token is not None and bool(self._provenance_signature)
