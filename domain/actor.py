# domain/actor.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

class ActorType(Enum):
    """Typer af Actors i DOR."""
    HUMAN = auto()
    DIGITAL_EMPLOYEE = auto()
    SERVICE = auto()
    EXTERNAL = auto()

@dataclass
class Actor:
    """Repræsenterer en enhed, der kan udføre handlinger i DOR."""
    id: str
    type: ActorType
    identity: str
    role: Optional["RoleDefinition"] = None
    capabilities: List["Capability"] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    organization: Optional["Organization"] = None
    department: Optional["Department"] = None
    team: Optional["Team"] = None

    def add_capability(self, capability: "Capability") -> None:
        """Legacy compatibility helper; does not grant runtime authority."""
        if capability not in self.capabilities:
            self.capabilities.append(capability)

    def has_capability(self, capability_id: str) -> bool:
        """Legacy compatibility inspection; not a canonical authorization check."""
        return any(cap.id == capability_id for cap in self.capabilities)

    def can_perform(self, action: str) -> bool:
        """Legacy path is intentionally non-authoritative and never grants access."""
        return False

    def needs_approval_for(self, action: str) -> List[str]:
        """Legacy compatibility helper; authority is resolved outside Actor."""
        if not self.role:
            return []
        return self.role.needs_approval_from.get(action, [])
