# domain/capability.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum, auto

class CapabilityLevel(Enum):
    """Niveauer for Capabilities."""
    BEGINNER = auto()
    INTERMEDIATE = auto()
    ADVANCED = auto()
    EXPERT = auto()

@dataclass
class Capability:
    """Repræsenterer en evne, som en Actor kan have."""
    id: str  # f.eks. "python.fastapi.expert"
    name: str  # f.eks. "FastAPI Expert"
    description: str = ""
    level: CapabilityLevel = CapabilityLevel.BEGINNER
    certification: Optional[str] = None  # f.eks. "Verified by EIRA"
    used_by: List[str] = field(default_factory=list)  # Liste af Actor-ID'er, der bruger denne Capability
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    organization: Optional["Organization"] = None

    def add_user(self, actor_id: str) -> None:
        """Tilføj en Actor-ID til listen af brugere."""
        if actor_id not in self.used_by:
            self.used_by.append(actor_id)
