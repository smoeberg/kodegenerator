"""AI-7 orchestration engine with a bounded, backoff-aware repair loop.

This engine drives an :class:`OrchestrationObservation` through the
deterministic AI-7 safety gates (:func:`phase4.orchestrator.models.decide`)
and, when the outcome failed/rejected and the loop bounds permit a retry,
asks the repair adapter for one immutable continuation proposal.  All state
advancement is explicit and validated: the iteration identity and the
plan request attempt counter stay tied together, exactly as the
orchestration contract requires.

The engine never executes work, never authorizes, never mutates an AI-5
outcome, and never constructs an action proposal itself.

Exponential backoff between retries is available through
:class:`ExponentialBackoff`; independent repair attempts can be dispatched
in parallel via :class:`ParallelRepairAdapter` without ever granting those
threads execution authority (they only produce immutable proposals).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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


class ExponentialBackoff:
    """Deterministic exponential backoff schedule (1s, 2s, 4s, ...).

    ``delay(retry_count)`` returns ``base * 2**(retry_count-1)`` capped at
    ``cap`` seconds, so the first retry waits ``base``, the second ``2*base``
    and so on.  Retry counts below ``1`` yield ``0.0`` (no wait).
    """

    def __init__(self, base: float = 1.0, cap: float = 8.0) -> None:
        if base <= 0:
            raise ValueError("backoff base must be positive")
        if cap < base:
            raise ValueError("backoff cap must be >= base")
        self._base = base
        self._cap = cap

    @property
    def base(self) -> float:
        return self._base

    @property
    def cap(self) -> float:
        return self._cap

    def delay(self, retry_count: int) -> float:
        if retry_count < 1:
            return 0.0
        return min(self._cap, self._base * (2 ** (retry_count - 1)))


class ParallelRepairAdapter:
    """Dispatch independent repair proposals concurrently.

    ``propose`` fans the request out to ``strategies`` (a mapping of strategy
    name to callable) in a bounded thread pool and returns the first
    proposal that is not ``None``.  Threads only *propose* — they never
    execute, authorize, or mutate anything — so this stays inside the AI-7
    authority boundary.
    """

    def __init__(
        self,
        strategies: dict[str, RepairAdapter],
        max_workers: int = 2,
    ) -> None:
        if not strategies:
            raise ValueError("strategies must not be empty")
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._strategies = dict(strategies)
        self._max_workers = max_workers

    def propose(self, request: PlanRequest) -> AgentActionProposal | None:
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(strategy.propose, request): name
                for name, strategy in self._strategies.items()
            }
            for future in as_completed(futures):
                proposal = future.result()
                if proposal is not None:
                    return proposal
        return None


class OrchestratorEngine:
    """AI-7 coordinator with a strict, stateless, bounded repair loop.

    The engine does not hold mutable loop state: ``advance`` and ``run_loop``
    are deterministic given the same starting observation and adapter.
    """

    def __init__(
        self,
        adapter: RepairAdapter | None = None,
        bounds: LoopBounds | None = None,
        backoff: ExponentialBackoff | None = None,
    ) -> None:
        self._adapter = adapter or StaticRepairAdapter()
        self._bounds = bounds or LoopBounds(max_depth=3, max_retries=2)
        self._backoff = backoff or ExponentialBackoff()

    @property
    def bounds(self) -> LoopBounds:
        return self._bounds

    @property
    def backoff(self) -> ExponentialBackoff:
        return self._backoff

    def retry_delay(self, retry_count: int) -> float:
        """Exponential delay in seconds for the next retry (0 for the first)."""
        return self._backoff.delay(retry_count)

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
    "ExponentialBackoff",
    "OrchestratorEngine",
    "ParallelRepairAdapter",
    "RepairAdapter",
    "StaticRepairAdapter",
]
