"""Asynchronous webhook delivery for critical swarm events."""
from __future__ import annotations
import asyncio, hashlib, hmac, json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CRITICAL_EVENTS = frozenset(("PROJECT_COMPLETED", "TASK_FAILED_DLQ", "SECURITY_VIOLATION_BLOCKED", "CIRCUIT_BREAKER_OPEN"))

@dataclass(frozen=True)
class WebhookEndpoint:
    endpoint_id: str
    url: str
    secret: bytes
    subscribed_events: frozenset[str]

@dataclass(frozen=True)
class DeadLetterDelivery:
    endpoint_id: str
    url: str
    event: str
    payload: dict[str, Any]
    error: str
    attempts: int
    recorded_at: str

class WebhookDispatcher:
    def __init__(self, max_retries: int = 3, timeout: float = 5.0, base_delay: float = 0.5) -> None:
        self._max_retries = max_retries
        self._timeout = timeout
        self._base_delay = base_delay
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._dead_letters: list[DeadLetterDelivery] = []
        self._tasks: list[asyncio.Task] = []

    def register(self, endpoint_id: str, url: str, secret: bytes, events: set[str]) -> None:
        self._endpoints[endpoint_id] = WebhookEndpoint(
            endpoint_id=endpoint_id,
            url=url,
            secret=secret,
            subscribed_events=frozenset(events),
        )

    def dead_letters(self) -> list[DeadLetterDelivery]:
        return list(self._dead_letters)

    async def publish(self, event: str, payload: Mapping[str, Any]) -> None:
        for ep in self._endpoints.values():
            if event in ep.subscribed_events:
                task = asyncio.create_task(self._deliver(ep, event, dict(payload)))
                self._tasks.append(task)

    async def flush(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

    def _post(self, url: str, body: bytes, signature: str) -> int:
        req = Request(url, data=body, headers={"Content-Type": "application/json", "X-Swarm-Signature": signature}, method="POST")
        with urlopen(req, timeout=self._timeout) as resp:
            return resp.status

    async def _deliver(self, ep: WebhookEndpoint, event: str, payload: dict[str, Any]) -> None:
        body = json.dumps({"event": event, "payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()}).encode()
        sig = hmac.new(ep.secret, body, hashlib.sha256).hexdigest()
        attempts = 0
        last_error = ""
        while attempts <= self._max_retries:
            attempts += 1
            try:
                loop = asyncio.get_running_loop()
                status = await loop.run_in_executor(None, self._post, ep.url, body, sig)
                if status < 500:
                    return
                last_error = f"HTTP {status}"
            except Exception as e:
                last_error = str(e)
            if attempts <= self._max_retries:
                await asyncio.sleep(self._base_delay * (2 ** (attempts - 1)))
        self._dead_letters.append(DeadLetterDelivery(
            endpoint_id=ep.endpoint_id,
            url=ep.url,
            event=event,
            payload=payload,
            error=last_error,
            attempts=attempts,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        ))
