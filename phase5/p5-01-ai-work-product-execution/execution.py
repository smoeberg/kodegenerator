"""Execution runtime for the P5-00 work-product contract.

The runtime owns dispatch and lifecycle progression through SUBMITTED. The
agent owns only execution output; verification remains outside this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Tuple
from uuid import uuid4

from p5_00_loader import load_contract_api

api = load_contract_api()
ActorRole = api.ActorRole
DeliveryState = api.DeliveryState
LifecycleEvent = api.LifecycleEvent
WorkProductSubmission = api.WorkProductSubmission
AIWorkProductContract = api.AIWorkProductContract
append_event = api.append_event


class ExecutionError(ValueError):
    """Raised when an execution cannot safely satisfy the P5-00 boundary."""


class AgentExecutor(Protocol):
    """Minimal adapter contract for an AI agent implementation."""

    def execute(self, context: "ExecutionContext") -> WorkProductSubmission:
        ...


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    agent_id: str
    contract: AIWorkProductContract
    dispatched_at: datetime


@dataclass(frozen=True)
class ExecutionResult:
    """The only result P5-01 produces: a submitted work product and history."""

    execution_id: str
    submission: WorkProductSubmission
    events: Tuple[LifecycleEvent, ...]

    @property
    def state(self) -> DeliveryState:
        return api.derive_delivery_state(self.events)


class ExecutionEngine:
    """Dispatch a contract-bound agent execution and collect its submission."""

    def __init__(self, runtime_id: str = "p5-01-runtime") -> None:
        if not runtime_id:
            raise ExecutionError("runtime_id is required")
        self.runtime_id = runtime_id

    def execute(
        self,
        contract: AIWorkProductContract,
        agent_id: str,
        executor: AgentExecutor,
        *,
        execution_id: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionResult:
        if not contract.contract_fingerprint:
            raise ExecutionError("contract fingerprint is required")
        if not agent_id:
            raise ExecutionError("agent_id is required")

        execution_id = execution_id or str(uuid4())
        started = now or datetime.now(timezone.utc)
        context = ExecutionContext(
            execution_id=execution_id,
            agent_id=agent_id,
            contract=contract,
            dispatched_at=started,
        )

        events: Tuple[LifecycleEvent, ...] = ()
        events = append_event(events, LifecycleEvent(
            event_id=str(uuid4()),
            submission_id=execution_id,
            event_type=DeliveryState.DISPATCHED,
            actor_id=self.runtime_id,
            actor_role=ActorRole.RUNTIME,
            contract_fingerprint=contract.contract_fingerprint,
            occurred_at=started,
        ))
        events = append_event(events, LifecycleEvent(
            event_id=str(uuid4()),
            submission_id=execution_id,
            event_type=DeliveryState.IN_PROGRESS,
            actor_id=agent_id,
            actor_role=ActorRole.AGENT,
            contract_fingerprint=contract.contract_fingerprint,
            occurred_at=started,
        ))

        submission = executor.execute(context)
        if not isinstance(submission, WorkProductSubmission):
            raise ExecutionError("agent executor must return WorkProductSubmission")
        if submission.submission_id != execution_id:
            raise ExecutionError("submission_id must equal execution_id")
        if submission.agent_id != agent_id:
            raise ExecutionError("submission agent_id does not match dispatched agent")
        if submission.contract_fingerprint != contract.contract_fingerprint:
            raise ExecutionError("submission contract fingerprint mismatch")

        events = append_event(events, LifecycleEvent(
            event_id=str(uuid4()),
            submission_id=execution_id,
            event_type=DeliveryState.SUBMITTED,
            actor_id=agent_id,
            actor_role=ActorRole.AGENT,
            contract_fingerprint=contract.contract_fingerprint,
            occurred_at=submission.submitted_at,
        ))
        return ExecutionResult(execution_id=execution_id, submission=submission, events=events)
