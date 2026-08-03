# domain/team.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class Team:
    """Repræsenterer et team under en afdeling."""
    id: str
    name: str
    description: str = ""
    lead: Optional["Actor"] = None  # Teamleder
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    department: Optional["Department"] = None
    members: List["Actor"] = field(default_factory=list)
    backlog: List[str] = field(default_factory=list)  # Liste af opgave-ID'er
    policies: List["Policy"] = field(default_factory=list)

    def add_member(self, actor: "Actor") -> None:
        """Tilføj en Actor til teamet."""
        if actor not in self.members:
            self.members.append(actor)
            actor.team = self

    def add_task(self, task_id: str) -> None:
        """Tilføj en opgave til teamets backlog."""
        if task_id not in self.backlog:
            self.backlog.append(task_id)
