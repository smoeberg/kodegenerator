"""Immutable AI-7 orchestration contracts.

AI-7 coordinates an outcome back to AI-6.  It cannot propose work, issue
authority, execute work, or mutate the AI-5 outcome it observes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Optional, Tuple

from phase4.authority.models import AuthorityDecision, Decision
from phase4.outcome.models import OutcomeRecord, OutcomeStatus
from phase4.planner.models import PlanRequest


class OrchestrationDirective(str, Enum):
    """The only two results AI-7 may produce for an observed outcome."""

    CONTINUE = "continue"
    STOP = "stop"


class OrchestrationState(str, Enum):
    """AI-7 lifecycle states, including every fail-closed terminal state."""

    ACTIVE = "active"
    COMPLETED = "completed"
    AUTHORITY_DENIED = "authority_denied"
    AUTHORITY_UNVERIFIED = "authority_unverified"
    OUTCOME_UNKNOWN = "outcome_unknown"
    DUPLICATE_OUTCOME = "duplicate_outcome"
    DEPTH_LIMIT_REACHED = "depth_limit_reached"
    RETRY_LIMIT_REACHED = "retry_limit_reached"

    @property
    def terminal(self) -> bool:
        return self is not OrchestrationState.ACTIVE


class DecisionReason(str, Enum):
    """Stable reasons for an orchestration directive."""

    PLANNING_REQUIRED = "planning_required"
    OUTCOME_SUCCEEDED = "outcome_succeeded"
    AUTHORITY_DENIED = "authority_denied"
    AUTHORITY_MISSING = "authority_missing"
    AUTHORITY_INVALID = "authority_invalid"
    OUTCOME_UNKNOWN = "outcome_unknown"
    DUPLICATE_OUTCOME = "duplicate_outcome"
    REPLAYED_OUTCOME = "replayed_outcome"
    DEPTH_LIMIT_REACHED = "depth_limit_reached"
    RETRY_LIMIT_REACHED = "retry_limit_reached"


@dataclass(frozen=True)
class LoopBounds:
    """Hard AI-7 safety ceilings; neither budget may be unbounded."""

    max_depth: int = 1
    max_retries: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.max_depth, bool) or not isinstance(self.max_depth, int):
            raise TypeError("max_depth must be an integer")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise TypeError("max_retries must be an integer")
        if self.max_depth < 1:
            raise ValueError("max_depth must be at least one")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


@dataclass(frozen=True)
class IterationIdentity:
    """Stable correlation and monotonic identity for one loop iteration.

    ``number`` is one-based.  Every iteration after the first is one retry, so
    tying the counters together prevents either safety budget being bypassed
    by resetting only one counter.
    """

    run_id: str
    number: int = 1
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if isinstance(self.number, bool) or not isinstance(self.number, int):
            raise TypeError("number must be an integer")
        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
            raise TypeError("retry_count must be an integer")
        if self.number < 1:
            raise ValueError("number must be at least one")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        if self.retry_count != self.number - 1:
            raise ValueError("retry_count must equal number minus one")

    @property
    def iteration_id(self) -> str:
        payload = {
            "run_id": self.run_id,
            "number": self.number,
            "retry_count": self.retry_count,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OrchestrationObservation:
    """AI-5 outcome and existing AI-3 decision observed by AI-7.

    The PlanRequest is carried as the exact object that can be handed to AI-6.
    AI-7 does not construct an action proposal itself.
    """

    iteration: IterationIdentity
    plan_request: PlanRequest
    authority_decision: Optional[AuthorityDecision]
    processed_outcome_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan_request, PlanRequest):
            raise TypeError("plan_request must be an AI-6 PlanRequest")
        if not isinstance(self.plan_request.outcome, OutcomeRecord):
            raise TypeError("plan_request outcome must be an AI-5 OutcomeRecord")
        for name in ("outcome_id", "request_id"):
            value = getattr(self.outcome, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"outcome {name} must be non-empty")
        if self.plan_request.attempt != self.iteration.retry_count:
            raise ValueError("plan attempt must match iteration retry_count")
        if self.authority_decision is not None:
            if not isinstance(self.authority_decision, AuthorityDecision):
                raise TypeError("authority_decision must be an AI-3 AuthorityDecision")
            if self.authority_decision.request_id != self.outcome.request_id:
                raise ValueError("outcome request_id must match the authority decision")
            for name in ("action", "resource", "context_packet_id"):
                if getattr(self.authority_decision, name) != getattr(self.plan_request, name):
                    raise ValueError(
                        f"plan {name} must match the authority decision"
                    )
        if any(not isinstance(item, str) or not item.strip() for item in self.processed_outcome_ids):
            raise ValueError("processed outcome IDs must be non-empty strings")
        if len(self.processed_outcome_ids) != len(set(self.processed_outcome_ids)):
            raise ValueError("processed outcome IDs must be unique")

    @property
    def run_id(self) -> str:
        return self.iteration.run_id

    @property
    def outcome(self) -> OutcomeRecord:
        return self.plan_request.outcome

    @property
    def duplicate_outcome(self) -> bool:
        return self.outcome.outcome_id in self.processed_outcome_ids


@dataclass(frozen=True)
class PlannerHandoff:
    """The sole non-terminal AI-7 output: an unchanged request for AI-6."""

    run_id: str
    iteration_id: str
    plan_request: PlanRequest
    boundary: str = "AI-6"

    def __post_init__(self) -> None:
        for name in ("run_id", "iteration_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.plan_request, PlanRequest):
            raise TypeError("plan_request must be an AI-6 PlanRequest")
        if self.boundary != "AI-6":
            raise ValueError("the next boundary must be AI-6")

    @property
    def executable(self) -> bool:
        return False

    @property
    def authoritative(self) -> bool:
        return False


@dataclass(frozen=True)
class OrchestrationDecision:
    """Validated STOP or CONTINUE result for one observation."""

    observation: OrchestrationObservation
    bounds: LoopBounds
    directive: OrchestrationDirective
    state: OrchestrationState
    reason: DecisionReason
    handoff: Optional[PlannerHandoff] = None

    def __post_init__(self) -> None:
        expected_directive, expected_state, expected_reason = _classify(
            self.observation, self.bounds
        )
        if (self.directive, self.state, self.reason) != (
            expected_directive,
            expected_state,
            expected_reason,
        ):
            raise ValueError("decision violates the AI-7 orchestration contract")

        if self.directive is OrchestrationDirective.CONTINUE:
            if self.handoff is None:
                raise ValueError("CONTINUE requires an AI-6 handoff")
            if self.handoff.boundary != "AI-6":
                raise ValueError("CONTINUE must route through AI-6")
            if self.handoff.run_id != self.observation.run_id:
                raise ValueError("handoff run_id must preserve correlation")
            if self.handoff.iteration_id != self.observation.iteration.iteration_id:
                raise ValueError("handoff must preserve iteration identity")
            if self.handoff.plan_request is not self.observation.plan_request:
                raise ValueError("handoff must preserve the AI-6 PlanRequest unchanged")
            if self.state.terminal:
                raise ValueError("CONTINUE cannot use a terminal state")
        else:
            if self.handoff is not None:
                raise ValueError("STOP cannot contain a handoff")
            if not self.state.terminal:
                raise ValueError("STOP requires a terminal state")

    @property
    def run_id(self) -> str:
        return self.observation.run_id

    @property
    def iteration_id(self) -> str:
        return self.observation.iteration.iteration_id

    @property
    def outcome(self) -> OutcomeRecord:
        return self.observation.outcome

    @property
    def terminal(self) -> bool:
        return self.state.terminal

    @property
    def executable(self) -> bool:
        return False

    @property
    def authoritative(self) -> bool:
        return False


def decide(observation: OrchestrationObservation, bounds: LoopBounds) -> OrchestrationDecision:
    """Apply only AI-7's deterministic safety gates; never plan or execute."""

    directive, state, reason = _classify(observation, bounds)
    handoff = None
    if directive is OrchestrationDirective.CONTINUE:
        handoff = PlannerHandoff(
            run_id=observation.run_id,
            iteration_id=observation.iteration.iteration_id,
            plan_request=observation.plan_request,
        )
    return OrchestrationDecision(
        observation=observation,
        bounds=bounds,
        directive=directive,
        state=state,
        reason=reason,
        handoff=handoff,
    )


def _classify(
    observation: OrchestrationObservation,
    bounds: LoopBounds,
) -> Tuple[OrchestrationDirective, OrchestrationState, DecisionReason]:
    """Return the one contract-valid directive without invoking another agent."""

    if observation.duplicate_outcome:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.DUPLICATE_OUTCOME,
            DecisionReason.DUPLICATE_OUTCOME,
        )

    authority = observation.authority_decision
    if authority is None:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.AUTHORITY_UNVERIFIED,
            DecisionReason.AUTHORITY_MISSING,
        )
    if authority.decision is Decision.DENY:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.AUTHORITY_DENIED,
            DecisionReason.AUTHORITY_DENIED,
        )
    if authority.decision is not Decision.ALLOW:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.AUTHORITY_UNVERIFIED,
            DecisionReason.AUTHORITY_INVALID,
        )

    status = observation.outcome.status
    if status is OutcomeStatus.UNKNOWN:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.OUTCOME_UNKNOWN,
            DecisionReason.OUTCOME_UNKNOWN,
        )
    if status is OutcomeStatus.SUCCEEDED:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.COMPLETED,
            DecisionReason.OUTCOME_SUCCEEDED,
        )
    if status is OutcomeStatus.REPLAYED:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.DUPLICATE_OUTCOME,
            DecisionReason.REPLAYED_OUTCOME,
        )
    if status not in {OutcomeStatus.FAILED, OutcomeStatus.REJECTED}:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.OUTCOME_UNKNOWN,
            DecisionReason.OUTCOME_UNKNOWN,
        )

    if observation.iteration.number >= bounds.max_depth:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.DEPTH_LIMIT_REACHED,
            DecisionReason.DEPTH_LIMIT_REACHED,
        )
    if observation.iteration.retry_count >= bounds.max_retries:
        return (
            OrchestrationDirective.STOP,
            OrchestrationState.RETRY_LIMIT_REACHED,
            DecisionReason.RETRY_LIMIT_REACHED,
        )

    # FAILED and non-authority REJECTED outcomes may only be considered by
    # AI-6. CONTINUE means "handoff to planner", never "execute again".
    return (
        OrchestrationDirective.CONTINUE,
        OrchestrationState.ACTIVE,
        DecisionReason.PLANNING_REQUIRED,
    )
