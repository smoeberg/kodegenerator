"""Transactional outbox contract for durable event publication."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    event_type: str
    payload: dict[str, Any]
    aggregate_id: str | None = None
    correlation_id: str | None = None


class OutboxStore(Protocol):
    def append(self, event: OutboxEvent) -> None: ...
    def claim(self, limit: int = 100) -> list[OutboxEvent]: ...
    def mark_published(self, event_id: str) -> None: ...


class OutboxPublisher:
    """Publish events only after their durable transaction has committed."""

    def __init__(self, store: OutboxStore, publish: Any):
        self.store = store
        self.publish = publish

    def publish_batch(self, limit: int = 100) -> int:
        published = 0
        for event in self.store.claim(limit):
            self.publish(event)
            self.store.mark_published(event.id)
            published += 1
        return published
