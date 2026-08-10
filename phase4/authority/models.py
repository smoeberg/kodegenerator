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
    """A concrete authorization question; it does not contain an authority decision."""

    request_id: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    requested_at: str
    agent_role: Optional[str] = None
    context: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("request_id", "agent_identity", "action", "resource", "context_packet_id", "requested_at"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.agent_role is not None and not self.agent_role.strip():
            raise ValueError("agent_role must be non-empty when supplied")
        keys = [key for key, _ in self.context]
        if len(keys) != len(set(keys)):
            raise ValueError("context keys must be unique")

    @staticmethod
    def create(
        agent_identity: str,
        action: str,
        resource: str,
        context_packet_id: str,
        *,
        agent_role: Optional[str] = None,
        context: Mapping[str, str] | None = None,
    ) -> "AuthorityRequest":
        timestamp = datetime.now(timezone.utc).isoformat()
        canonical_context = sorted((str(k), str(v)) for k, v in (context or {}).items())
        identity_payload = {
            "agent_identity": agent_identity,
            "action": action,
            "resource": resource,
            "context_packet_id": context_packet_id,
            "agent_role": agent_role,
            "context": canonical_context,
        }
        encoded = json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
        request_id = hashlib.sha256(encoded).hexdigest()
        return AuthorityRequest(
            request_id=request_id,
            agent_identity=agent_identity,
            action=action,
            resource=resource,
            context_packet_id=context_packet_id,
            requested_at=timestamp,
            agent_role=agent_role,
            context=tuple(canonical_context),
        )


@dataclass(frozen=True)
class AuthorityRule:
    """One explicit policy rule. Rules never create capabilities or mutate identity."""

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
    """Immutable policy snapshot evaluated by the authority engine."""

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
    """Immutable, auditable result of an authority evaluation.

    ``_provenance_token`` is populated only by ``AuthorityEngine``. It is not a
    public constructor argument and is intentionally excluded from equality and
    representation so authority provenance cannot be recreated by copying the
    decision fields.
    """

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
    _provenance_token: object | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.agent_identity.strip():
            raise ValueError("request_id and agent_identity must be non-empty")
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def provenance_verified(self) -> bool:
        return self._provenance_token is not None
