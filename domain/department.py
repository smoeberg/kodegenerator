# domain/department.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class Department:
    """Repræsenterer en afdeling i en organisation."""
    id: str
    name: str
    description: str = ""
    manager: Optional["Actor"] = None  # Afdelingsleder
    budget: float = 0.0  # Årligt budget
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    organization: Optional["Organization"] = None
    teams: List["Team"] = field(default_factory=list)
    actors: List["Actor"] = field(default_factory=list)
    policies: List["Policy"] = field(default_factory=list)

    def add_team(self, team: "Team") -> None:
        """Tilføj et team til afdelingen."""
        if team not in self.teams:
            self.teams.append(team)
            team.department = self

    def add_actor(self, actor: "Actor") -> None:
        """Tilføj en Actor til afdelingen."""
        if actor not in self.actors:
            self.actors.append(actor)
            actor.department = self

    def add_policy(self, policy: "Policy") -> None:
        """Tilføj en policy til afdelingen."""
        if policy not in self.policies:
            self.policies.append(policy)
