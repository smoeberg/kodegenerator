# domain/governance.py
"""
Governance Domain Model

Represents the governance structure and boards that oversee DOR operations.
Governance is a first-class concern in DOR and is integrated from the foundation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime
from enum import Enum, auto
import uuid

if TYPE_CHECKING:
    from domain.actor import Actor
    from domain.organization import Organization
    from domain.artifact import Artifact, ArtifactState, GovernanceState, Signature
    from domain.policy import Policy


class BoardType(Enum):
    """Types of Governance Boards."""
    ARCHITECTURE = auto()
    SECURITY = auto()
    COMPLIANCE = auto()
    QUALITY = auto()
    ETHICS = auto()
    FINANCIAL = auto()
    OPERATIONS = auto()


class DecisionStatus(Enum):
    """Status of a Governance Decision."""
    PENDING = auto()
    APPROVED = auto()
    REJECTED = auto()
    DEFERRED = auto()
    EXEMPT = auto()


@dataclass
class GovernanceDecision:
    """Represents a decision made by a Governance Board."""
    board_type: BoardType
    artifact_id: Optional[str] = None
    decision: DecisionStatus = DecisionStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    comments: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    voting_record: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    actor_id: Optional[str] = None

    def is_approved(self) -> bool:
        return self.decision == DecisionStatus.APPROVED

    def is_rejected(self) -> bool:
        return self.decision == DecisionStatus.REJECTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "board_type": self.board_type.name,
            "artifact_id": self.artifact_id,
            "decision": self.decision.name,
            "comments": self.comments,
            "evidence": self.evidence,
            "voting_record": self.voting_record,
            "timestamp": self.timestamp.isoformat(),
            "actor_id": self.actor_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceDecision":
        return cls(
            board_type=BoardType[data["board_type"]],
            artifact_id=data.get("artifact_id"),
            decision=DecisionStatus[data.get("decision", "PENDING")],
            id=data.get("id", str(uuid.uuid4())),
            comments=data.get("comments", ""),
            evidence=data.get("evidence", {}),
            voting_record=data.get("voting_record", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.utcnow(),
            actor_id=data.get("actor_id")
        )


@dataclass
class GovernanceBoard:
    """Represents a Governance Board (e.g., Architecture Board, Security Board)."""
    board_type: BoardType
    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization: Optional["Organization"] = None
    description: str = ""
    members: List["Actor"] = field(default_factory=list)
    policies: List["Policy"] = field(default_factory=list)
    decisions: List[GovernanceDecision] = field(default_factory=list)
    quorum: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_member(self, actor: "Actor") -> None:
        if actor not in self.members:
            self.members.append(actor)
            self.updated_at = datetime.utcnow()

    def remove_member(self, actor: "Actor") -> None:
        if actor in self.members:
            self.members.remove(actor)
            self.updated_at = datetime.utcnow()

    def has_quorum(self) -> bool:
        return len(self.members) >= self.quorum

    def can_decide(self, actor: "Actor") -> bool:
        return actor in self.members

    def make_decision(self, artifact: "Artifact", decision: DecisionStatus, actor: "Actor", comments: str = "", evidence: Optional[Dict[str, Any]] = None) -> GovernanceDecision:
        if not self.can_decide(actor):
            raise NotAuthorizedError(f"Actor {actor.id} is not a member of this board")
        
        governance_decision = GovernanceDecision(
            board_type=self.board_type,
            artifact_id=artifact.id,
            decision=decision,
            id=str(uuid.uuid4()),
            comments=comments,
            evidence=evidence or {},
            actor_id=actor.id
        )
        
        self.decisions.append(governance_decision)
        self.updated_at = datetime.utcnow()
        
        return governance_decision

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "board_type": self.board_type.name,
            "name": self.name,
            "description": self.description,
            "organization_id": self.organization.id if self.organization else None,
            "member_ids": [m.id for m in self.members],
            "policy_ids": [p.id for p in self.policies],
            "quorum": self.quorum,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "GovernanceBoard":
        return cls(
            board_type=BoardType[data["board_type"]],
            name=data["name"],
            id=data.get("id", str(uuid.uuid4())),
            description=data.get("description", ""),
            quorum=data.get("quorum", 1),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            organization=None,
            members=[],
            policies=[],
            decisions=[],
            **kwargs
        )


@dataclass
class GovernanceDepartment:
    """Represents the Governance Department of an Organization."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Governance Department"
    organization: Optional["Organization"] = None
    boards: Dict[BoardType, GovernanceBoard] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def get_board(self, board_type: BoardType) -> Optional[GovernanceBoard]:
        return self.boards.get(board_type)

    def add_board(self, board: GovernanceBoard) -> None:
        if board.board_type not in self.boards:
            self.boards[board.board_type] = board
            board.organization = self.organization
            self.updated_at = datetime.utcnow()

    def remove_board(self, board_type: BoardType) -> None:
        if board_type in self.boards:
            del self.boards[board_type]
            self.updated_at = datetime.utcnow()

    def approve_artifact(self, artifact: "Artifact", board_type: BoardType, actor: "Actor", comments: str = "") -> bool:
        board = self.get_board(board_type)
        if not board:
            return False
        
        if not board.can_decide(actor):
            return False
        
        decision = board.make_decision(
            artifact=artifact,
            decision=DecisionStatus.APPROVED,
            actor=actor,
            comments=comments
        )
        
        artifact.add_signature(Signature(
            role_id=f"{board_type.name.lower()}_reviewer",
            actor_id=actor.id,
            status="approved",
            comments=comments
        ))
        
        if artifact.is_approved():
            artifact.state = ArtifactState.APPROVED
            artifact.governance_state = GovernanceState.APPROVED
        else:
            artifact.state = ArtifactState.IN_REVIEW
        
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "organization_id": self.organization.id if self.organization else None,
            "boards": {k.name: v.to_dict() for k, v in self.boards.items()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "GovernanceDepartment":
        boards = {}
        for board_type_str, board_data in data.get("boards", {}).items():
            board_type = BoardType[board_type_str]
            boards[board_type] = GovernanceBoard.from_dict(board_data)
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Governance Department"),
            boards=boards,
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            organization=None,
            **kwargs
        )


class NotAuthorizedError(Exception):
    """Raised when an Actor is not authorized to perform an action."""
    pass
