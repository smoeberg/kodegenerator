# domain/policy.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class Policy:
    """Repræsenterer en global regel, der håndhæves i DOR."""
    id: str
    name: str
    description: str = ""
    scope: str = "global"  # "global", "department:<id>", "team:<id>"
    conditions: Dict[str, any] = field(default_factory=dict)  # Betingelser (f.eks. {"min_coverage": 0.9})
    actions: Dict[str, str] = field(default_factory=dict)  # Handlinger (f.eks. {"on_violation": "block"})
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    organization: Optional["Organization"] = None

    def applies_to(self, target: str) -> bool:
        """Tjek om policyen gælder for et givet mål (f.eks. workflow, artifact, actor)."""
        if self.scope == "global":
            return True
        elif self.scope.startswith("department:"):
            return target.startswith(f"department:{self.scope.split(':')[1]}")
        elif self.scope.startswith("team:"):
            return target.startswith(f"team:{self.scope.split(':')[1]}")
        return False
