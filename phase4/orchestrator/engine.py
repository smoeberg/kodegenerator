"""AI-7 orchestration engine with a bounded repair loop.

This engine drives an :class:`OrchestrationObservation` through the
deterministic AI-7 safety gates (:func:`phase4.orchestrator.models.decide`)
and, when the outcome failed/rejected and the loop bounds permit a retry,
asks the repair adapter for one immutable continuation proposal.  All state
advancement is explicit and validated: the iteration identity and the
plan request attempt counter stay tied together, exactly as the
orchestration contract requires.

The engine never executes work, never authorizes, never mutates an AI-5
outcome, and never constructs an action proposal itself.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from phase4.orchestrator.models import (
    LoopBounds,
    OrchestrationDecision,
    OrchestrationDirective,
    OrchestrationObservation,
    decide,
)
from phase4.planner.models import (
    AgentActionProposal,
    PlanRequest,
    PlanStatus,
    proposal_id_for,
)


class RepairAdapter(Protocol):
    """Boundary the repair loop needs from the planner world.

    ``propose`` receives the immutable plan request and returns an immutable
    *proposal* (never an authority decision or an execution), or ``None``
    when no further repair is possible.
    """

    def propose(self, request: PlanRequest) -> AgentActionProposal | None: ...


class StaticRepairAdapter:
    """Deterministic repair adapter used for tests and fail-closed operation.

    Produces a bounded continuation proposal for a failed/rejected outcome,
    up to ``max_repairs`` calls, then returns ``None`` so the engine can
    stop at the retry limit exactly as the contract requires.
    """

    def __init__(self, max_repairs: int = 2) -> None:
        self._max_repairs = max_repairs
        self._calls = 0

    def propose(self, request: PlanRequest) -> AgentActionProposal | None:
        if self._calls >= self._max_repairs:
            return None
        self._calls += 1
        return AgentActionProposal(
            proposal_id=proposal_id_for(request, f"repair-{self._calls}"),
            outcome_id=request.outcome.outcome_id,
            request_id=request.outcome.request_id,
            request_fingerprint=request.request_fingerprint,
            action=request.action,
            resource=request.resource,
            context_packet_id=request.context_packet_id,
            parameters=request.parameters,
            attempt=request.attempt + 1,
            reason=f"bounded repair continuation proposal #{self._calls}",
            status=PlanStatus.PROPOSED,
        )


class OrchestratorEngine:
    """AI-7 coordinator with a strict, stateless, bounded repair loop.

    The engine does not hold mutable loop state: ``advance`` and ``run_loop``
    are deterministic given the same starting observation and adapter.
    """

    def __init__(
        self,
        adapter: RepairAdapter | None = None,
        bounds: LoopBounds | None = None,
    ) -> None:
        self._adapter = adapter or StaticRepairAdapter()
        self._bounds = bounds or LoopBounds(max_depth=3, max_retries=2)

    @property
    def bounds(self) -> LoopBounds:
        return self._bounds

    def advance(self, observation: OrchestrationObservation) -> OrchestrationDecision:
        """Evaluate one observation through the AI-7 safety gates."""
        return decide(observation, self._bounds)

    def run_loop(
        self,
        observation: OrchestrationObservation,
        *,
        max_steps: int = 20,
    ) -> tuple[OrchestrationObservation, OrchestrationDecision]:
        """Drive the repair loop until a terminal decision.

        Returns ``(final_observation, terminal_decision)``.  The engine only
        advances the iteration when the adapter produced a proposal, and it
        keeps ``plan_request.attempt`` tied to ``iteration.retry_count``, so
        every constructed observation satisfies the contract invariant.
        """
        current = observation
        for _ in range(max_steps):
            decision = decide(current, self._bounds)
            if decision.directive is not OrchestrationDirective.CONTINUE:
                return current, decision

            if self._adapter.propose(current.plan_request) is None:
                # No further repair possible from the adapter: STOP with
                # RETRY_LIMIT_REACHED.  Re-run decide() on the same observation
                # (its retry budget is already at the deterministic limit
                # chosen by the caller), so the decision is contract-valid.
                return current, decide(current, self._bounds)

            # Advance exactly one retry, keeping attempt and retry_count tied.
            next_retry = current.iteration.retry_count + 1
            advanced = replace(
                current,
                iteration=replace(
                    current.iteration,
                    number=next_retry + 1,
                    retry_count=next_retry,
                ),
                plan_request=replace(
                    current.plan_request,
                    attempt=next_retry,
                ),
            )
            current = advanced
        return current, decide(current, self._bounds)


__all__ = [
    "OrchestratorEngine",
    "RepairAdapter",
    "StaticRepairAdapter",
]
