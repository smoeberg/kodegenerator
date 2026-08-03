# domain/governance.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class GovernanceDepartment:
    """Repræsenterer en Governance-afdeling med boards (Architecture, Security, etc.)."""
    id: str
    name: str = "Governance Department"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Relationer
    organization: Optional["Organization"] = None
    architecture_board: List["Actor"] = field(default_factory=list)
    security_board: List["Actor"] = field(default_factory=list)
    compliance_board: List["Actor"] = field(default_factory=list)
    quality_board: List["Actor"] = field(default_factory=list)
    ethics_board: List["Actor"] = field(default_factory=list)
    financial_board: List["Actor"] = field(default_factory=list)

    def add_to_board(self, board_name: str, actor: "Actor") -> None:
        """Tilføj en Actor til et bestemt board."""
        board = getattr(self, f"{board_name}_board", None)
        if board and actor not in board:
            board.append(actor)

    def get_board(self, board_name: str) -> List["Actor"]:
        """Hent et board (f.eks. "architecture_board")."""
        return getattr(self, f"{board_name}_board", [])

    def approve_artifact(self, artifact: "Artifact", board_name: str) -> bool:
        """Godkend et Artifact via et bestemt board."""
        board = self.get_board(board_name)
        if not board:
            return False
        # Tjek om alle medlemmer af boardet har godkendt
        required_roles = [f"{board_name}_reviewer" for _ in board]
        for sig in artifact.signatures:
            if sig.role_id in required_roles and sig.status == "approved":
                required_roles.remove(sig.role_id)
        return len(required_roles) == 0
