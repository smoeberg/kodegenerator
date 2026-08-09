"""Append-only lifecycle events and derived delivery state."""

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


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    submission_id: str
    event_type: DeliveryState
    actor_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.event_id or not self.submission_id or not self.actor_id:
            raise ValueError("event identity is required")
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

_P3_20_ONLY = {DeliveryState.VERIFYING, DeliveryState.PASSED, DeliveryState.FAILED}


def derive_delivery_state(events: Tuple[LifecycleEvent, ...]) -> DeliveryState:
    """Derive state from an append-only event sequence; never from agent input."""
    if not events:
        return DeliveryState.DRAFT
    state = DeliveryState.DRAFT
    for event in events:
        if event.event_type not in _ALLOWED[state]:
            raise ValueError(f"invalid lifecycle transition: {state.value} -> {event.event_type.value}")
        state = event.event_type
    return state


def append_event(events: Tuple[LifecycleEvent, ...], event: LifecycleEvent) -> Tuple[LifecycleEvent, ...]:
    """Validate and append one lifecycle event without mutating prior history."""
    if events and events[-1].submission_id != event.submission_id:
        raise ValueError("lifecycle event submission mismatch")
    if event.event_type in _P3_20_ONLY and event.actor_id != "p3-20":
        raise PermissionError("only p3-20 may enter or resolve verification")
    if not events and event.event_type is not DeliveryState.DISPATCHED:
        raise ValueError("first persisted transition must be DISPATCHED")
    derive_delivery_state(events + (event,))
    return events + (event,)
