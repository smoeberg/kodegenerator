# domain/event.py
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime
from enum import Enum, auto

class EventType(Enum):
    """Typer af Events."""
    INTENT_CREATED = auto()
    WORKFLOW_STARTED = auto()
    STATE_CHANGED = auto()
    ARTIFACT_CREATED = auto()
    ARTIFACT_APPROVED = auto()
    ARTIFACT_REJECTED = auto()
    TASK_ASSIGNED = auto()
    TASK_COMPLETED = auto()
    POLICY_VIOLATED = auto()
    GOVERNANCE_APPROVAL = auto()
    MODEL_SWAPPED = auto()

@dataclass
class Event:
    """Repræsenterer en hændelse i DOR (audit, læring, memory)."""
    id: str
    event_type: EventType
    actor: Optional["Actor"] = None
    artifact: Optional["Artifact"] = None
    workflow: Optional["Workflow"] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)  # Yderligere data (f.eks. {"old_state": "NEW", "new_state": "ANALYSIS"})

    def to_dict(self) -> Dict:
        """Konverter Event til et dictionary (for logging/serialisering)."""
        return {
            "id": self.id,
            "type": self.event_type.name,
            "actor_id": self.actor.id if self.actor else None,
            "artifact_id": self.artifact.id if self.artifact else None,
            "workflow_id": self.workflow.id if self.workflow else None,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }
