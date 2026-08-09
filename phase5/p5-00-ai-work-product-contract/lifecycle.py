"""Append-only lifecycle events and derived delivery state.

Lifecycle state is never an agent-controlled field. Every event binds to the
same dispatched contract fingerprint, and authority is explicit per event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Tuple


class DeliveryState(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ActorRole(str, Enum):
    AGENT = "agent"
    RUNTIME = "runtime"
    VERIFICATION_RUNTIME = "verification-runtime"
    P3_20 = "p3-20"


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    submission_id: str
    event_type: DeliveryState
    actor_id: str
    occurred_at: datetime
    contract_fingerprint: str = ""
    actor_role: ActorRole = ActorRole.AGENT

    def __post_init__(self) -> None:
        if not self.event_id or not self.submission_id or not self.actor_id:
            raise ValueError("event identity is required")
        if not self.contract_fingerprint:
            raise ValueError("lifecycle event must bind to a contract fingerprint")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=timezone.utc))


_ALLOWED = {
    DeliveryState.DRAFT: {DeliveryState.DISPATCHED},
    DeliveryState.DISPATCHED: {DeliveryState.IN_PROGRESS},
    DeliveryState.IN_PROGRESS: {DeliveryState.SUBMITTED},
    DeliveryState.SUBMITTED: {DeliveryState.VERIFYING},
    DeliveryState.VERIFYING: {DeliveryState.PASSED, DeliveryState.FAILED},
    DeliveryState.PASSED: set(),
    DeliveryState.FAILED: set(),
}


def _role_allowed(event: LifecycleEvent) -> bool:
    if event.event_type is DeliveryState.DISPATCHED:
        return event.actor_role is ActorRole.RUNTIME
    if event.event_type in {DeliveryState.IN_PROGRESS, DeliveryState.SUBMITTED}:
        return event.actor_role in {ActorRole.AGENT, ActorRole.RUNTIME}
    if event.event_type is DeliveryState.VERIFYING:
        return event.actor_role is ActorRole.VERIFICATION_RUNTIME
    if event.event_type in {DeliveryState.PASSED, DeliveryState.FAILED}:
        return event.actor_role is ActorRole.P3_20 and event.actor_id == "p3-20"
    return False


def derive_delivery_state(events: Tuple[LifecycleEvent, ...]) -> DeliveryState:
    """Derive state from an append-only event sequence; never from agent input."""
    if not events:
        return DeliveryState.DRAFT
    state = DeliveryState.DRAFT
    contract_fingerprint = events[0].contract_fingerprint
    for event in events:
        if event.contract_fingerprint != contract_fingerprint:
            raise ValueError("lifecycle event contract fingerprint mismatch")
        if event.event_type not in _ALLOWED[state]:
            raise ValueError(f"invalid lifecycle transition: {state.value} -> {event.event_type.value}")
        if not _role_allowed(event):
            raise PermissionError(f"actor role is not authorized for {event.event_type.value}")
        state = event.event_type
    return state


def append_event(events: Tuple[LifecycleEvent, ...], event: LifecycleEvent) -> Tuple[LifecycleEvent, ...]:
    """Validate and append one lifecycle event without mutating prior history."""
    if events and events[-1].submission_id != event.submission_id:
        raise ValueError("lifecycle event submission mismatch")
    if events and events[-1].contract_fingerprint != event.contract_fingerprint:
        raise ValueError("lifecycle event contract fingerprint mismatch")
    if not events and event.event_type is not DeliveryState.DISPATCHED:
        raise ValueError("first persisted transition must be DISPATCHED")
    derive_delivery_state(events + (event,))
    return events + (event,)
