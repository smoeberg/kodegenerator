# domain/actor.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

class ActorType(Enum):
    """Typer af Actors i DOR."""
    HUMAN = auto()          # Menneske (f.eks. John Doe)
    DIGITAL_EMPLOYEE = auto()  # AI-medarbejder (f.eks. Claude-5)
    SERVICE = auto()        # Service (f.eks. GitHub Bot)
    EXTERNAL = auto()       # Ekstern system (f.eks. Kundeportal)

@dataclass
class Actor:
    """Repræsenterer en enhed, der kan udføre handlinger i DOR."""
    id: str
    type: ActorType
    identity: str  # f.eks. "Claude-5", "John Doe", "GitHub Bot"
    role: Optional["RoleDefinition"] = None
    capabilities: List["Capability"] = field(default_factory=list)
    status: str = "active"  # "active", "inactive", "suspended"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    organization: Optional["Organization"] = None
    department: Optional["Department"] = None
    team: Optional["Team"] = None

    def add_capability(self, capability: "Capability") -> None:
        """Tilføj en Capability til Actor."""
        if capability not in self.capabilities:
            self.capabilities.append(capability)

    def has_capability(self, capability_id: str) -> bool:
        """Tjek om Actor har en given Capability."""
        return any(cap.id == capability_id for cap in self.capabilities)

    def can_perform(self, action: str) -> bool:
        """Tjek om Actor kan udføre en given handling (baseret på RoleDefinition)."""
        if not self.role:
            return False
        return self.role.authority.get(f"can_{action}", False)

    def needs_approval_for(self, action: str) -> List[str]:
        """Hent liste af roller, der skal godkende en given handling."""
        if not self.role:
            return []
        return self.role.needs_approval_from.get(action, [])
