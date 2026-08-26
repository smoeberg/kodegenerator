"""Non-blocking Human Approval Queue for Phase 4."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from infrastructure.runtime.queue import DatabaseQueue, QueueMessage


@dataclass(frozen=True)
class ApprovalEnvelope:
    approval_id: str
    task_id: str
    title: str
    description: str
    requested_by: str
    payload: dict[str, Any]
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXPIRED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HumanApprovalQueue:
    """Manages asynchronous human-in-the-loop approvals without blocking agent execution."""

    TOPIC_HUMAN_APPROVALS = "human.approvals"

    def __init__(self, db_queue: DatabaseQueue) -> None:
        self.db_queue = db_queue

    def request_approval(
        self,
        task_id: str,
        title: str,
        description: str,
        requested_by: str,
        payload: dict[str, Any] | None = None
    ) -> str:
        """Enqueue an approval request non-blockingly so agents can move to other tasks."""
        approval_id = str(uuid4())
        envelope = {
            "approval_id": approval_id,
            "task_id": task_id,
            "title": title,
            "description": description,
            "requested_by": requested_by,
            "payload": payload or {},
            "status": "PENDING",
            "requested_at": datetime.now(timezone.utc).isoformat()
        }
        return self.db_queue.publish(self.TOPIC_HUMAN_APPROVALS, envelope, message_id=approval_id)

    def poll_pending_approvals(self, worker_id: str = "admin-ui-poller") -> Optional[QueueMessage]:
        """Admin interface or notification service polls for pending human approvals."""
        return self.db_queue.claim(self.TOPIC_HUMAN_APPROVALS, worker_id)

    def resolve_approval(self, message_id: str, worker_id: str, approved: bool, resolved_by: str, comment: str = "") -> None:
        """Approve or reject a pending request and acknowledge the queue item."""
        resolution_data = {
            "status": "APPROVED" if approved else "REJECTED",
            "resolved_by": resolved_by,
            "comment": comment,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }
        self.db_queue.ack(message_id, worker_id)
