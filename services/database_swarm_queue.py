"""Swarm task contract backed by the canonical tenant-scoped database queue."""

from __future__ import annotations

from typing import Any

from infrastructure.runtime.queue import DatabaseQueue, QueueMessage
from services.swarm_task_queue import QueuedTask, QueuedTaskStatus, SwarmTaskQueue


class DatabaseSwarmTaskQueue:
    """Durable implementation of the existing dependency-aware swarm API."""

    topic = "swarm.task"

    def __init__(self, queue: DatabaseQueue) -> None:
        self._queue = queue
        self.lease_seconds = queue.lease_seconds

    def enqueue_wbs_plan(self, plan: Any) -> int:
        created = 0
        for item in SwarmTaskQueue._extract_tasks(plan):
            task = SwarmTaskQueue._normalise_task(item)
            payload = {
                "task_id": task.task_id,
                "name": task.name,
                "dependencies": list(task.dependencies),
                "capabilities": list(task.capabilities),
                "priority": task.priority,
                "max_retries": task.max_retries,
                "metadata": task.metadata,
            }
            before = self._queue.get(self._message_id(task.task_id))
            self._queue.publish(
                self.topic, payload, message_id=self._message_id(task.task_id)
            )
            created += before is None
        return created

    def claim_next_task(
        self, agent_id: str, capabilities: list[str]
    ) -> QueuedTask | None:
        available = set(capabilities)

        def eligible(payload: dict[str, Any]) -> bool:
            if not set(payload.get("capabilities", [])).issubset(available):
                return False
            return all(
                (dependency := self._queue.get(self._message_id(str(dep)))) is not None
                and dependency.status == "completed"
                for dep in payload.get("dependencies", [])
            )

        message = self._queue.claim(
            self.topic,
            agent_id,
            eligible=eligible,
            order_key=lambda payload: (
                -int(payload.get("priority", 0)),
                str(payload["task_id"]),
            ),
        )
        return self._task(message) if message is not None else None

    def heartbeat(self, task_id: str, agent_id: str) -> None:
        message = self._owned(task_id, agent_id)
        self._queue.heartbeat(message.id, agent_id, message.lease_id or "")

    def complete_task(self, task_id: str, agent_id: str, patch_result: Any) -> None:
        message = self._owned(task_id, agent_id)
        result = (
            patch_result if isinstance(patch_result, dict) else {"value": patch_result}
        )
        self._queue.ack(message.id, agent_id, message.lease_id or "", result)

    def fail_task(
        self, task_id: str, agent_id: str, error: str, retry: bool = True
    ) -> None:
        message = self._owned(task_id, agent_id)
        self._queue.fail(
            message.id,
            agent_id,
            message.lease_id or "",
            error,
            retry_after_seconds=0,
            retry=retry,
        )

    def pending_count(self) -> int:
        return self._queue.pending_count(self.topic)

    def get_task(self, task_id: str) -> QueuedTask:
        message = self._queue.get(self._message_id(task_id))
        if message is None:
            raise KeyError(task_id)
        return self._task(message)

    def list_tasks(self) -> list[QueuedTask]:
        return [self._task(message) for message in self._queue.list(self.topic)]

    def _owned(self, task_id: str, agent_id: str) -> QueueMessage:
        message = self._queue.get(self._message_id(task_id))
        if (
            message is None
            or message.status != "leased"
            or message.worker_id != agent_id
        ):
            raise PermissionError("task is not claimed by this agent")
        return message

    @staticmethod
    def _message_id(task_id: str) -> str:
        return f"swarm:{task_id}"

    @staticmethod
    def _task(message: QueueMessage) -> QueuedTask:
        payload = message.payload
        statuses = {
            "pending": QueuedTaskStatus.PENDING,
            "leased": QueuedTaskStatus.CLAIMED,
            "completed": QueuedTaskStatus.COMPLETED,
            "dead_letter": QueuedTaskStatus.FAILED,
        }
        result = payload.get("completion_result")
        return QueuedTask(
            task_id=str(payload["task_id"]),
            name=str(payload["name"]),
            dependencies=tuple(payload.get("dependencies", [])),
            capabilities=tuple(payload.get("capabilities", [])),
            priority=int(payload.get("priority", 0)),
            status=statuses[message.status],
            agent_id=message.worker_id if message.status == "leased" else None,
            lease_expires_at=message.lease_until,
            retry_count=max(0, message.attempts - 1),
            max_retries=int(payload.get("max_retries", 3)),
            error=message.last_error,
            patch_result=result,
            metadata=dict(payload.get("metadata", {})),
        )
