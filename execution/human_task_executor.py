# execution/human_task_executor.py
from typing import Dict, Any
from domain.task import Task, TaskStatus
from domain.actor import Actor, ActorType
from runtime.event_bus import EventBus
from domain.event import Event, EventType
from datetime import datetime

class HumanTaskExecutor:
    """Udfører tasks, der kræver menneskelig indgriben (f.eks. godkendelser)."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def execute(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """
        Udfør en Task, der kræver menneskelig indgriben.
        Sender en notifikation til Actor (f.eks. via email, Slack).
        """
        if actor.type != ActorType.HUMAN:
            return {"status": "failed", "error": "Actor is not a Human"}

        # Simuler notifikation (i praksis ville dette være email, Slack, etc.)
        notification = {
            "task_id": task.id,
            "task_name": task.name,
            "task_description": task.description,
            "actor_id": actor.id,
            "actor_name": actor.identity,
            "message": f"Du har en ny opgave: {task.name}. Beskrivelse: {task.description}"
        }

        # Log Event (Notifikation sendt)
        self.event_bus.publish(Event(
            id=f"event_{len(self.event_bus.events) + 1}",
            event_type=EventType.TASK_ASSIGNED,
            actor=actor,
            metadata={"notification": notification},
            timestamp=datetime.now(timezone.utc)
        ))

        # Vent på menneskelig handling (simuleret)
        # I praksis ville vi vente på en callback (f.eks. fra en UI)
        return {
            "status": "pending",
            "message": "Notification sent to human actor",
            "notification": notification
        }
