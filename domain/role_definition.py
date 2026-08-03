# domain/role_definition.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class RoleDefinition:
    """Definerer en stilling (kompetencer, ansvar, autoritet, begrænsninger)."""
    id: str
    name: str
    description: str = ""
    department_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Kompetencer
    capabilities: List[str] = field(default_factory=list)  # Liste af Capability-ID'er

    # Autoritet
    authority: Dict[str, bool] = field(default_factory=dict)  # f.eks. {"can_approve": True, "can_reject": False}
    needs_approval_from: Dict[str, List[str]] = field(default_factory=dict)  # f.eks. {"merge_to_main": ["architecture_reviewer", "qa"]}

    # Ansvar
    responsibilities: List[str] = field(default_factory=list)

    # Relationer
    organization: Optional["Organization"] = None

    def add_capability(self, capability_id: str) -> None:
        """Tilføj en Capability-ID til rollen."""
        if capability_id not in self.capabilities:
            self.capabilities.append(capability_id)

    def can_perform(self, action: str) -> bool:
        """Tjek om rollen kan udføre en given handling."""
        return self.authority.get(f"can_{action}", False)

    def get_required_approvals(self, action: str) -> List[str]:
        """Hent liste af roller, der skal godkende en given handling."""
        return self.needs_approval_from.get(action, [])
