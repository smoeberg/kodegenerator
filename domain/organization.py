# domain/organization.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class Organization:
    """Repræsenterer en juridisk/operationel identitet (f.eks. EIRA, Acme Corp)."""
    id: str
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    departments: List["Department"] = field(default_factory=list)
    actors: List["Actor"] = field(default_factory=list)
    policies: List["Policy"] = field(default_factory=list)
    governance: Optional["GovernanceDepartment"] = None

    def add_department(self, department: "Department") -> None:
        """Tilføj en afdeling til organisationen."""
        if department not in self.departments:
            self.departments.append(department)
            department.organization = self

    def add_actor(self, actor: "Actor") -> None:
        """Tilføj en Actor til organisationen."""
        if actor not in self.actors:
            self.actors.append(actor)
            actor.organization = self

    def add_policy(self, policy: "Policy") -> None:
        """Tilføj en policy til organisationen."""
        if policy not in self.policies:
            self.policies.append(policy)

    def set_governance(self, governance: "GovernanceDepartment") -> None:
        """Sæt Governance Department for organisationen."""
        self.governance = governance
        governance.organization = self
