"""Dedicated Project Manager & Orchestrator Inbox Queue for Phase 4."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from infrastructure.runtime.queue import DatabaseQueue, QueueMessage


@dataclass(frozen=True)
class PMTaskEnvelope:
    task_id: str
    title: str
    description: str
    priority: str  # "low", "medium", "high", "urgent"
    assigned_role: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProjectManagerInbox:
    """Specialized queue management for the Project Manager AI Orchestrator.
    
    Ensures the PM bot has a durable, prioritized inbox for incoming human tasks,
    specialist progress reports, council deadlock escalations, and verification results.
    """

    TOPIC_PM_INBOX = "pm.inbox"
    TOPIC_SPECIALIST_DISPATCH = "pm.dispatch.specialist"
    TOPIC_ESCALATIONS = "pm.escalations"

    def __init__(self, db_queue: DatabaseQueue) -> None:
        self.db_queue = db_queue

    def receive_task(self, task_id: str, title: str, description: str, priority: str, payload: dict[str, Any] | None = None) -> str:
        """Enqueue an incoming task or brief into the PM inbox."""
        msg_id = str(uuid4())
        envelope = {
            "task_id": task_id,
            "title": title,
            "description": description,
            "priority": priority,
            "payload": payload or {},
            "received_at": datetime.now(timezone.utc).isoformat()
        }
        # Priority mapping to available_at or message ordering if needed
        return self.db_queue.publish(self.TOPIC_PM_INBOX, envelope, message_id=msg_id)

    def dispatch_to_specialist(self, task_id: str, target_role: str, instruction: str, context: dict[str, Any] | None = None) -> str:
        """PM dispatches a sub-task or challenge to a specialist bot (e.g. Coder, SecuritySkeptic)."""
        msg_id = str(uuid4())
        dispatch_packet = {
            "task_id": task_id,
            "target_role": target_role,
            "instruction": instruction,
            "context": context or {},
            "dispatched_at": datetime.now(timezone.utc).isoformat()
        }
        return self.db_queue.publish(self.TOPIC_SPECIALIST_DISPATCH, dispatch_packet, message_id=msg_id)

    def escalate_deadlock(self, session_id: str, task_id: str, reason: str) -> str:
        """PM escalates a council deadlock or stuck loop for human review or authority intervention."""
        msg_id = str(uuid4())
        escalation_packet = {
            "session_id": session_id,
            "task_id": task_id,
            "reason": reason,
            "escalated_at": datetime.now(timezone.utc).isoformat()
        }
        return self.db_queue.publish(self.TOPIC_ESCALATIONS, escalation_packet, message_id=msg_id)

    def poll_pm_inbox(self, worker_id: str = "pm-orchestrator-bot") -> Optional[QueueMessage]:
        """PM polls its inbox for incoming tasks/briefs."""
        return self.db_queue.claim(self.TOPIC_PM_INBOX, worker_id)

    def poll_specialist_dispatch(self, worker_id: str) -> Optional[QueueMessage]:
        """Specialist bot polls for dispatches assigned by PM."""
        return self.db_queue.claim(self.TOPIC_SPECIALIST_DISPATCH, worker_id)

    def ack_message(self, message_id: str, worker_id: str) -> None:
        """Acknowledge successful processing of a message."""
        self.db_queue.ack(message_id, worker_id)

    def fail_message(self, message_id: str, worker_id: str, error: str) -> None:
        """Mark message processing as failed for retry/requeue."""
        self.db_queue.fail(message_id, worker_id, error)
