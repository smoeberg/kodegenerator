"""Deterministic Phase 4 verification policy evaluation.

This module evaluates verification observations already produced by workers.
It deliberately does not call an LLM, select agents, persist state, or grant
execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from phase4.contracts import KnowledgeState, VerificationMode, VerificationPolicy


class VerificationResult(str, Enum):
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    INSUFFICIENT = "insufficient"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class VerificationEngine:
    """Evaluate verifier outcomes against a VerificationPolicy.

    The engine is intentionally pure: callers own persistence and any
    subsequent KnowledgeState transition.
    """

    def evaluate(
        self,
        policy: VerificationPolicy,
        outcomes: Iterable[bool],
    ) -> VerificationResult:
        votes = tuple(outcomes)

        if policy.mode is VerificationMode.DETERMINISTIC:
            if len(votes) != 1:
                return VerificationResult.INSUFFICIENT
            return (
                VerificationResult.CONFIRMED
                if votes[0]
                else VerificationResult.DISPUTED
            )

        if policy.mode is VerificationMode.SINGLE_AGENT:
            if len(votes) != 1:
                return VerificationResult.INSUFFICIENT
            return (
                VerificationResult.CONFIRMED
                if votes[0]
                else VerificationResult.DISPUTED
            )

        if policy.mode is VerificationMode.QUORUM:
            if len(votes) < policy.quorum_size:
                return VerificationResult.INSUFFICIENT
            quorum = votes[: policy.quorum_size]
            if all(quorum):
                return VerificationResult.CONFIRMED
            if not any(quorum):
                return VerificationResult.DISPUTED
            return VerificationResult.ESCALATE

        if policy.mode is VerificationMode.HUMAN:
            if not votes:
                return VerificationResult.INSUFFICIENT
            return (
                VerificationResult.CONFIRMED
                if votes[-1]
                else VerificationResult.DISPUTED
            )

        raise ValueError(f"Unsupported verification mode: {policy.mode}")


def result_to_state(result: VerificationResult) -> KnowledgeState | None:
    """Map a verification result to a materialized knowledge state."""
    if result is VerificationResult.CONFIRMED:
        return KnowledgeState.CONFIRMED
    if result is VerificationResult.DISPUTED:
        return KnowledgeState.DISPUTED
    return None
