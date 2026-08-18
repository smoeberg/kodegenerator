"""Verified authority credentials for the Phase 4 execution boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import AuthorityDecision


@dataclass(frozen=True)
class VerifiedAuthorityGrant:
    """Non-forgeable-in-contract authority credential issued from AI-3 provenance.

    The private issuer token is deliberately not part of the public constructor.
    A hand-constructed grant therefore cannot become verified merely by copying
    the fields of an existing authority decision.
    """

    request_id: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    policy_id: str
    policy_version: str
    matched_rule_ids: tuple[str, ...]
    decision: str
    parameters: tuple[tuple[str, str], ...] = ()
    _issuer_token: object | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_decision(cls, decision: AuthorityDecision) -> "VerifiedAuthorityGrant":
        token = getattr(decision, "_provenance_token", None)
        if token is None or decision.decision.value != "allow":
            raise ValueError("authority decision has no verified AI-3 provenance")
        grant = cls(
            request_id=decision.request_id,
            agent_identity=decision.agent_identity,
            action=decision.action,
            resource=decision.resource,
            context_packet_id=decision.context_packet_id,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            matched_rule_ids=decision.matched_rule_ids,
            decision=decision.decision.value,
            parameters=decision.parameters,
        )
        object.__setattr__(grant, "_issuer_token", token)
        return grant

    @property
    def verified(self) -> bool:
        return self._issuer_token is not None

    def binds(self, request: Any) -> bool:
        return (
            self.verified
            and self.request_id == request.request_id
            and self.agent_identity == request.agent_identity
            and self.action == request.action
            and self.resource == request.resource
            and self.context_packet_id == request.context_packet_id
            and self.parameters == tuple(request.parameters)
        )
