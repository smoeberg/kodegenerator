"""Durable execution dispatcher and worker primitives for Phase 7."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from infrastructure.runtime.queue import DurableQueue, QueueMessage


class ExecutionHandler(Protocol):
    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class ExecutionDispatcher:
    """Enqueue executions without executing work in the API process."""

    def __init__(self, queue: DurableQueue):
        self.queue = queue

    def dispatch(self, execution_id: str, payload: dict[str, Any]) -> QueueMessage:
        return self.queue.enqueue(
            kind="execution",
            payload={"execution_id": execution_id, "payload": payload},
            dedupe_key=f"execution:{execution_id}",
        )


class ExecutionWorker:
    """Claim and execute one durable execution at a time.

    The handler must be idempotent. Queue acknowledgement happens only after
    the handler returns successfully, so a crash before ack causes redelivery.
    """

    def __init__(self, queue: DurableQueue, handler: ExecutionHandler):
        self.queue = queue
        self.handler = handler

    def run_once(self, worker_id: str, lease_seconds: int = 60) -> ExecutionResult | None:
        message = self.queue.claim(worker_id=worker_id, lease_seconds=lease_seconds)
        if message is None:
            return None

        execution_id = str(message.payload["execution_id"])
        try:
            result = self.handler(dict(message.payload["payload"]))
            self.queue.ack(message.id, worker_id)
            return ExecutionResult(execution_id=execution_id, status="succeeded", result=result)
        except Exception as exc:  # noqa: BLE001 - failure becomes durable retry
            self.queue.fail(message.id, worker_id, str(exc))
            return ExecutionResult(execution_id=execution_id, status="failed", error=str(exc))
