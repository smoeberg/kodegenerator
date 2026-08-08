"""AI-6 policy/planner engine.

The planner decides whether a continuation is worth proposing. It has no
adapter registry, authority engine, or execution capability by design.
"""
from __future__ import annotations

from typing import Dict, Optional

from phase4.outcome.models import OutcomeStatus
from .models import AgentActionProposal, ContinuationPolicy, PlanRequest, PlanStatus, proposal_id_for


class AgentPlanner:
    """Deterministic, side-effect-free continuation planner."""

    def __init__(self, policy: Optional[ContinuationPolicy] = None) -> None:
        self.policy = policy or ContinuationPolicy()
        self._proposals: Dict[str, AgentActionProposal] = {}

    def plan(self, request: PlanRequest) -> Optional[AgentActionProposal]:
        status = request.outcome.status

        if status is OutcomeStatus.UNKNOWN:
            return None

        if status is OutcomeStatus.SUCCEEDED:
            return None

        if status not in self.policy.retryable_statuses:
            return None

        next_attempt = request.attempt + 1
        if next_attempt > self.policy.max_retries:
            return None

        reason = f"retry after {status.value} outcome"
        proposal_id = proposal_id_for(request, reason)
        existing = self._proposals.get(proposal_id)
        if existing is not None:
            return existing

        proposal = AgentActionProposal(
            proposal_id=proposal_id,
            outcome_id=request.outcome.outcome_id,
            request_id=request.outcome.request_id,
            request_fingerprint=request.request_fingerprint,
            action=request.action,
            resource=request.resource,
            context_packet_id=request.context_packet_id,
            parameters=tuple(sorted(request.parameters)),
            attempt=next_attempt,
            reason=reason,
            status=PlanStatus.PROPOSED,
        )
        self._proposals[proposal_id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Optional[AgentActionProposal]:
        return self._proposals.get(proposal_id)
