# runtime/event_bus.py
from typing import Dict, List, Callable, Optional
from domain.event import Event, EventType
from domain.actor import Actor
from domain.artifact import Artifact
from domain.workflow import Workflow

class EventBus:
    """Distribuerer Events til subscribers."""

    def __init__(self):
        self.events: List[Event] = []
        self.subscribers: Dict[EventType, List[Callable]] = {}

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """Abonner på en EventType."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event: Event) -> None:
        """Publicer et Event til alle subscribers."""
        self.events.append(event)
        if event.event_type in self.subscribers:
            for callback in self.subscribers[event.event_type]:
                callback(event)

    def get_events(self, event_type: Optional[EventType] = None) -> List[Event]:
        """Hent alle Events (eller filtreret på type)."""
        if event_type:
            return [e for e in self.events if e.event_type == event_type]
        return self.events
