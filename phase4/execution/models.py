"""Phase 4 AI-4 execution domain models.

AI-4 consumes an already-issued AI-3 AuthorityDecision. It never creates
or interprets authority itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple
import hashlib
import json

from phase4.authority.models import AuthorityDecision


class ExecutionStatus(str, Enum):
    """Terminal status of an execution attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class ExecutionRequest:
    """Concrete work item submitted to AI-4.

    AI-4 requires the security-relevant subject attributes to match the AI-3
    decision exactly before an adapter can be called.
    """

    request_id: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    parameters: Tuple[Tuple[str, str], ...] = ()
    idempotency_key: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "request_id", "agent_identity", "action", "resource", "context_packet_id"
        ):
            value = getattr(self, name)
            if not value or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        keys = [key for key, _ in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("parameter keys must be unique")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must be non-empty when supplied")

    @staticmethod
    def create(
        request_id: str,
        agent_identity: str,
        action: str,
        resource: str,
        context_packet_id: str,
        *,
        parameters: Mapping[str, str] | None = None,
        idempotency_key: Optional[str] = None,
    ) -> "ExecutionRequest":
        canonical = tuple(sorted((str(k), str(v)) for k, v in (parameters or {}).items()))
        return ExecutionRequest(
            request_id=request_id,
            agent_identity=agent_identity,
            action=action,
            resource=resource,
            context_packet_id=context_packet_id,
            parameters=canonical,
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Immutable result and audit record produced by AI-4."""

    execution_id: str
    request_id: str
    authority_policy_id: str
    authority_policy_version: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    status: ExecutionStatus
    adapter_id: str
    output: Tuple[Tuple[str, str], ...]
    error: Optional[str]
    executed_at: str

    @property
    def succeeded(self) -> bool:
        return self.status is ExecutionStatus.SUCCEEDED

    @property
    def terminal(self) -> bool:
        return self.status in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.REPLAYED,
        }


def execution_id_for(request: ExecutionRequest, decision: AuthorityDecision) -> str:
    """Return a stable execution identity bound to the exact authority result."""
    payload = {
        "request_id": request.request_id,
        "agent_identity": request.agent_identity,
        "action": request.action,
        "resource": request.resource,
        "context_packet_id": request.context_packet_id,
        "parameters": sorted(list(request.parameters)),
        "idempotency_key": request.idempotency_key,
        "authority_decision": decision.decision.value,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "matched_rule_ids": list(decision.matched_rule_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
