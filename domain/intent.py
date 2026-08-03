# domain/intent.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

class IntentPriority(Enum):
    """Prioritetsniveauer for Intents."""
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()

@dataclass
class Intent:
    """Repræsenterer et mål eller ønsket resultat, der udløser et Workflow."""
    id: str
    goal: str  # f.eks. "Implement OAuth2"
    description: str = ""
    priority: IntentPriority = IntentPriority.MEDIUM
    constraints: Dict[str, any] = field(default_factory=dict)  # f.eks. {"security_level": "high"}
    required_capabilities: List[str] = field(default_factory=list)  # Liste af Capability-ID'er
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    creator: Optional["Actor"] = None
    workflow: Optional["Workflow"] = None
    organization: Optional["Organization"] = None

    def matches_actor(self, actor: "Actor") -> bool:
        """Tjek om en Actor kan håndtere denne Intent (baseret på Capabilities)."""
        return all(
            actor.has_capability(cap_id)
            for cap_id in self.required_capabilities
        )
