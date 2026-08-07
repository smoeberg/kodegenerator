# domain/intent.py
"""
Intent Domain Model

Represents a goal or desired outcome that triggers a Workflow.
Intents are the entry point for all DOR operations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum, auto
import uuid


class IntentPriority(Enum):
    """Priority levels for Intents."""
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


class IntentStatus(Enum):
    """Status of an Intent."""
    CREATED = auto()
    PROCESSING = auto()
    RESOLVED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class Intent:
    """
    Represents a goal or desired result that triggers a Workflow.
    
    An Intent is the entry point for all DOR operations. It captures
    the "what" (goal) and "why" (description) before determining the "how"
    (Workflow).
    """
    id: str
    goal: str
    description: str = ""
    priority: IntentPriority = IntentPriority.MEDIUM
    constraints: Dict[str, any] = field(default_factory=dict)
    required_capabilities: List[str] = field(default_factory=list)
    status: IntentStatus = IntentStatus.CREATED
    
    # Relationships
    creator: Optional["Actor"] = None
    organization: Optional["Organization"] = None
    workflow: Optional["Workflow"] = None
    
    # Metadata
    metadata: Dict[str, any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Initialize with default ID if not provided."""
        if not hasattr(self, 'id') or self.id is None:
            object.__setattr__(self, 'id', str(uuid.uuid4()))

    def matches_actor(self, actor: "Actor") -> bool:
        """Check if an Actor can handle this Intent based on required capabilities."""
        if not actor:
            return False
        return all(
            actor.has_capability(cap_id)
            for cap_id in self.required_capabilities
        )

    def resolve_workflow(self, workflows: List["Workflow"]) -> Optional["Workflow"]:
        """Find the most appropriate Workflow for this Intent."""
        if not workflows:
            return None
        
        goal_lower = self.goal.lower()
        for workflow in workflows:
            if workflow.name.lower() == goal_lower:
                return workflow
        
        for workflow in workflows:
            if goal_lower in workflow.name.lower() or workflow.name.lower() in goal_lower:
                return workflow
        
        return workflows[0] if workflows else None

    def to_dict(self) -> Dict[str, any]:
        """Convert Intent to dictionary for serialization."""
        return {
            "id": self.id,
            "goal": self.goal,
            "description": self.description,
            "priority": self.priority.name,
            "status": self.status.name,
            "constraints": self.constraints,
            "required_capabilities": self.required_capabilities,
            "creator_id": self.creator.id if self.creator else None,
            "organization_id": self.organization.id if self.organization else None,
            "workflow_id": self.workflow.id if self.workflow else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, any], **kwargs) -> "Intent":
        """Create Intent from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            goal=data["goal"],
            description=data.get("description", ""),
            priority=IntentPriority[data.get("priority", "MEDIUM")],
            constraints=data.get("constraints", {}),
            required_capabilities=data.get("required_capabilities", []),
            status=IntentStatus[data.get("status", "CREATED")],
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(timezone.utc),
            **kwargs
        )
