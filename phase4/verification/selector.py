"""Deterministic verifier selection over the existing AgentRegistry."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from phase4.agent_registry import AgentIdentity, AgentRecord, AgentRegistry, AgentRole


@dataclass(frozen=True)
class VerifierSelection:
    claim_id: str
    policy_id: str
    candidate_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    seed: str
    reason: str


class VerifierSelector:
    """Select active, capable agents reproducibly without owning agent identity."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def select(
        self,
        *,
        claim_id: str,
        policy_id: str,
        quorum_size: int,
        role: AgentRole | None = None,
        capability: str | None = None,
    ) -> VerifierSelection:
        if not claim_id:
            raise ValueError("claim_id must be non-empty")
        if not policy_id:
            raise ValueError("policy_id must be non-empty")
        if quorum_size < 1:
            raise ValueError("quorum_size must be positive")

        candidates = self._registry.list(role=role, capability=capability)
        candidate_ids = tuple(sorted(str(agent.identity) for agent in candidates))
        if len(candidate_ids) < quorum_size:
            raise ValueError("insufficient eligible verifier candidates")

        seed = hashlib.sha256(
            f"{claim_id}:{policy_id}".encode("utf-8")
        ).hexdigest()
        ranked = sorted(
            candidate_ids,
            key=lambda identity: hashlib.sha256(
                f"{seed}:{identity}".encode("utf-8")
            ).hexdigest(),
        )
        selected_ids = tuple(ranked[:quorum_size])
        return VerifierSelection(
            claim_id=claim_id,
            policy_id=policy_id,
            candidate_ids=candidate_ids,
            selected_ids=selected_ids,
            seed=seed,
            reason="active eligible agents deterministically ranked from claim and policy",
        )
