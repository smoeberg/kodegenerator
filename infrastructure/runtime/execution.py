"""Phase 7 durable execution dispatch over the database queue."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from infrastructure.runtime.queue import DatabaseQueue, QueueMessage


class ExecutionHandler(Protocol):
    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class ExecutionDispatcher:
    """Enqueue executions; never execute application work in the API process."""

    def __init__(self, queue: DatabaseQueue):
        self.queue = queue

    def dispatch(self, execution_id: str, payload: dict[str, Any]) -> QueueMessage:
        message_id = self.queue.publish(
            topic="execution",
            payload={"execution_id": execution_id, "payload": payload},
            message_id=f"execution:{execution_id}",
        )
        return QueueMessage(
            message_id,
            self.queue.organization_id,
            "execution",
            {"execution_id": execution_id, "payload": payload},
            0,
        )


class ExecutionWorker:
    """Claim durable executions and delegate them to the governed handler."""

    def __init__(self, queue: DatabaseQueue, handler: ExecutionHandler):
        self.queue = queue
        self.handler = handler

    def run_once(self, worker_id: str) -> ExecutionResult | None:
        message = self.queue.claim(topic="execution", worker_id=worker_id)
        if message is None:
            return None

        execution_id = str(message.payload["execution_id"])
        if not message.lease_id:
            raise RuntimeError("claimed queue message is missing its lease fence")
        try:
            result = self.handler(dict(message.payload["payload"]))
            self.queue.ack(message.id, worker_id, message.lease_id)
            return ExecutionResult(execution_id, "succeeded", result=result)
        except Exception as exc:  # noqa: BLE001 - durable retry is intentional
            self.queue.fail(message.id, worker_id, message.lease_id, str(exc))
            return ExecutionResult(execution_id, "failed", error=str(exc))
