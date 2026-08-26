"""In-process EventBus with topic pub/sub for swarm real-time updates.

Topics follow the convention:

* ``project:{project_id}`` — task/worker events scoped to a project
* ``worker:{worker_id}`` — single-worker stream
* ``system:alerts`` — cross-cutting alerts (circuit breaker, DLQ, security)

The bus is process-local and thread-safe. WebSocket/SSE hubs and optional
``WebhookDispatcher`` / ``OperationsMetrics`` adapters subscribe here without
coupling to transport details.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, DefaultDict, Mapping
from uuid import uuid4

Subscriber = Callable[[str, Mapping[str, Any]], Awaitable[None] | None]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class BusEvent:
    """Immutable event envelope published on the bus."""

    event_id: str
    topic: str
    event_type: str
    payload: Mapping[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


@dataclass
class EventBus:
    """Pub/sub event bus with topic routing and optional fan-out adapters."""

    _subs: DefaultDict[str, list[tuple[str, Subscriber]]] = field(
        default_factory=lambda: defaultdict(list), repr=False
    )
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _history: list[BusEvent] = field(default_factory=list, repr=False)
    _history_limit: int = 500
    _webhook_dispatcher: Any | None = field(default=None, repr=False)
    _operations_metrics: Any | None = field(default=None, repr=False)

    def bind_webhook_dispatcher(self, dispatcher: Any) -> None:
        """Attach a WebhookDispatcher-like object (``async publish(event, payload)``)."""
        self._webhook_dispatcher = dispatcher

    def bind_operations_metrics(self, metrics: Any) -> None:
        """Attach OperationsMetrics for optional side-channel updates."""
        self._operations_metrics = metrics

    def subscribe(self, topic: str, callback: Subscriber) -> str:
        """Register ``callback`` for ``topic``. Returns subscription id."""
        sub_id = str(uuid4())
        with self._lock:
            self._subs[topic].append((sub_id, callback))
        return sub_id

    def unsubscribe(self, topic: str, subscription_id: str) -> bool:
        """Remove a subscription. Returns True if found."""
        with self._lock:
            entries = self._subs.get(topic, [])
            kept = [(sid, cb) for sid, cb in entries if sid != subscription_id]
            if len(kept) == len(entries):
                return False
            self._subs[topic] = kept
            return True

    def publish(
        self,
        topic: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> BusEvent:
        """Publish an event to ``topic`` and notify local subscribers."""
        event = BusEvent(
            event_id=str(uuid4()),
            topic=topic,
            event_type=event_type,
            payload=dict(payload or {}),
            timestamp=_utc_iso(),
        )
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit :]
            subscribers = list(self._subs.get(topic, []))
            # Also deliver system:alerts to any broader listeners already on topic
            if topic.startswith("project:") or topic.startswith("worker:"):
                subscribers = subscribers + list(self._subs.get("system:alerts", []))

        for _sid, callback in subscribers:
            try:
                result = callback(event_type, event.to_dict())
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        asyncio.run(result)
            except Exception:
                # Never let a bad subscriber break the publisher.
                continue

        self._fanout_webhook(event)
        self._touch_metrics(event)
        return event

    def recent(
        self,
        topic: str | None = None,
        limit: int = 50,
    ) -> list[BusEvent]:
        """Return recent events, optionally filtered by topic."""
        with self._lock:
            items = list(self._history)
        if topic is not None:
            items = [e for e in items if e.topic == topic]
        return items[-limit:]

    def topics(self) -> list[str]:
        """List topics that currently have at least one subscriber."""
        with self._lock:
            return sorted(t for t, subs in self._subs.items() if subs)

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic, []))

    def clear(self) -> None:
        """Drop all subscriptions and history (tests)."""
        with self._lock:
            self._subs.clear()
            self._history.clear()

    def _fanout_webhook(self, event: BusEvent) -> None:
        dispatcher = self._webhook_dispatcher
        if dispatcher is None:
            return
        try:
            result = dispatcher.publish(event.event_type, event.to_dict())
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    result.close()  # type: ignore[attr-defined]
        except Exception:
            return

    def _touch_metrics(self, event: BusEvent) -> None:
        """Best-effort signal to OperationsMetrics when DLQ/alert events fire."""
        metrics = self._operations_metrics
        if metrics is None:
            return
        try:
            if event.event_type in ("TASK_FAILED_DLQ", "DLQ_ENQUEUE") and hasattr(
                metrics, "bind_dlq_size"
            ):
                size = int(event.payload.get("dlq_size", 0))
                if size:
                    metrics.bind_dlq_size(size)
        except Exception:
            return


# Process-wide default bus used by the WebSocket/SSE hub.
default_event_bus = EventBus()


def project_topic(project_id: str) -> str:
    """Canonical project topic name."""
    return f"project:{project_id}"


def worker_topic(worker_id: str) -> str:
    """Canonical worker topic name."""
    return f"worker:{worker_id}"


SYSTEM_ALERTS_TOPIC = "system:alerts"
