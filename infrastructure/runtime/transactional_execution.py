"""Atomic task receipt + queue dispatch for Phase 7."""
from __future__ import annotations

from domain.task_execution import TaskExecutionReceipt, TaskExecutionRequest
from infrastructure.persistence.task_execution_repository import TaskExecutionRepository
from infrastructure.runtime.queue import DatabaseQueue, QueueMessage


class TransactionalExecutionDispatcher:
    """Persist the canonical execution receipt and work item in one transaction.

    This uses the queue table as a transactional outbox. The worker may only
    observe the message after the surrounding transaction commits.
    """

    def __init__(self, queue: DatabaseQueue):
        self.queue = queue

    def dispatch(self, session, request: TaskExecutionRequest) -> QueueMessage:
        repository = TaskExecutionRepository(session)
        existing = repository.get(request.execution_id, request.organization_id)
        if existing is not None:
            return QueueMessage(
                id=f"execution:{request.execution_id}",
                topic="execution",
                payload=self._payload(request),
                attempts=0,
            )

        receipt = TaskExecutionReceipt(
            execution_id=request.execution_id,
            organization_id=request.organization_id,
            actor_id=request.actor_id,
            task_type=request.task_type,
            capability_id=request.capability_id,
            payload=request.payload,
            resource_id=request.resource_id,
            resource_organization_id=request.resource_organization_id,
        )
        repository.add(receipt)
        message_id = self.queue.enqueue_in_session(
            session,
            topic="execution",
            payload=self._payload(request),
            message_id=f"execution:{request.execution_id}",
        )
        return QueueMessage(message_id, "execution", self._payload(request), 0)

    @staticmethod
    def _payload(request: TaskExecutionRequest) -> dict:
        return {
            "execution_id": request.execution_id,
            "organization_id": request.organization_id,
            "actor_id": request.actor_id,
            "task_type": request.task_type,
            "capability_id": request.capability_id,
            "payload": dict(request.payload),
            "resource_id": request.resource_id,
            "resource_organization_id": request.resource_organization_id,
        }
