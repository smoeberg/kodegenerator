"""Asynchronous webhook delivery for critical swarm events."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .secure_http import validate_http_url

CRITICAL_EVENTS = frozenset(("PROJECT_COMPLETED", "TASK_FAILED_DLQ", "SECURITY_VIOLATION_BLOCKED", "CIRCUIT_BREAKER_OPEN"))


@dataclass(frozen=True)
class WebhookEndpoint:
    """Registered webhook destination and signing secret."""
    endpoint_id: str
    url: str
    secret: bytes
    subscribed_events: frozenset[str]


@dataclass(frozen=True)
class DeadLetterDelivery:
    """Auditable failed webhook delivery."""
    endpoint_id: str
    url: str
    event: str
    payload: dict[str, Any]
    error: str
    attempts: int
    recorded_at: str


class WebhookDispatcher:
    """Dispatch signed events while rejecting non-HTTP(S) destinations."""

    def __init__(self, max_retries: int = 3, timeout: float = 5.0, base_delay: float = 0.5) -> None:
        self._max_retries = max_retries
        self._timeout = timeout
        self._base_delay = base_delay
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._dead_letters: list[DeadLetterDelivery] = []
        self._tasks: list[asyncio.Task[None]] = []

    def register(self, endpoint_id: str, url: str, secret: bytes, events: set[str]) -> None:
        """Register a webhook after validating that its URL is HTTP or HTTPS."""
        self._endpoints[endpoint_id] = WebhookEndpoint(endpoint_id, validate_http_url(url), secret, frozenset(events))

    def dead_letters(self) -> list[DeadLetterDelivery]:
        """Return a snapshot of failed deliveries."""
        return list(self._dead_letters)

    async def publish(self, event: str, payload: Mapping[str, Any]) -> None:
        """Schedule delivery to all endpoints subscribed to the event."""
        for endpoint in self._endpoints.values():
            if event in endpoint.subscribed_events:
                task = asyncio.create_task(self._deliver(endpoint, event, dict(payload)))
                self._tasks.append(task)

    async def flush(self) -> None:
        """Wait for all scheduled deliveries."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

    def _post(self, url: str, body: bytes, signature: str) -> int:
        """POST a signed payload to a validated HTTP(S) destination."""
        safe_url = validate_http_url(url)
        request = Request(safe_url, data=body, headers={"Content-Type": "application/json", "X-Swarm-Signature": signature}, method="POST")
        with urlopen(request, timeout=self._timeout) as response:  # nosec B310 - URL is explicitly restricted to HTTP(S).
            return response.status

    async def _deliver(self, endpoint: WebhookEndpoint, event: str, payload: dict[str, Any]) -> None:
        """Deliver an event with bounded exponential retry and dead-letter recording."""
        body = json.dumps({"event": event, "payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()}).encode()
        signature = hmac.new(endpoint.secret, body, hashlib.sha256).hexdigest()
        attempts = 0
        last_error = ""
        while attempts <= self._max_retries:
            attempts += 1
            try:
                loop = asyncio.get_running_loop()
                status = await loop.run_in_executor(None, self._post, endpoint.url, body, signature)
                if status < 500:
                    return
                last_error = f"HTTP {status}"
            except Exception as exc:
                last_error = str(exc)
            if attempts <= self._max_retries:
                await asyncio.sleep(self._base_delay * (2 ** (attempts - 1)))
        self._dead_letters.append(DeadLetterDelivery(endpoint.endpoint_id, endpoint.url, event, payload, last_error, attempts, datetime.now(timezone.utc).isoformat()))
