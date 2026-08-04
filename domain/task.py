# domain/task.py
"""
Task Domain Model

Represents a unit of work to be executed within a Workflow.
Tasks are the atomic units of execution in DOR.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime
from enum import Enum, auto
import uuid

if TYPE_CHECKING:
    from domain.actor import Actor
    from domain.workflow import Workflow
    from domain.artifact import Artifact
    from domain.organization import Organization


class TaskStatus(Enum):
    """Status of a Task."""
    PENDING = auto()
    READY = auto()
    CLAIMED = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    BLOCKED = auto()
    CANCELLED = auto()
    RETRYING = auto()


class TaskPriority(Enum):
    """Priority levels for Tasks."""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class DependencyStatus(Enum):
    """Status of Task dependencies."""
    WAITING_FOR_DEPENDENCY = auto()
    READY = auto()


@dataclass
class Task:
    """Represents a unit of work to be executed within a Workflow."""
    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    dependency_status: DependencyStatus = DependencyStatus.WAITING_FOR_DEPENDENCY
    priority: TaskPriority = TaskPriority.MEDIUM
    workflow_id: Optional[str] = None
    organization_id: Optional[str] = None
    
    dependencies: List[str] = field(default_factory=list)
    assigned_actor: Optional["Actor"] = None
    input_artifacts: List[str] = field(default_factory=list)
    output_artifacts: List[str] = field(default_factory=list)
    
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    execution_parameters: Dict[str, Any] = field(default_factory=dict)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not hasattr(self, 'id') or self.id is None:
            object.__setattr__(self, 'id', str(uuid.uuid4()))

    def can_start(self, completed_tasks: List[str]) -> bool:
        return all(dep_id in completed_tasks for dep_id in self.dependencies)

    def is_blocked(self, completed_tasks: List[str]) -> bool:
        return not self.can_start(completed_tasks)

    def update_dependency_status(self, completed_tasks: List[str]) -> None:
        if self.can_start(completed_tasks):
            self.dependency_status = DependencyStatus.READY
        else:
            self.dependency_status = DependencyStatus.WAITING_FOR_DEPENDENCY

    def assign_to(self, actor: "Actor") -> None:
        self.assigned_actor = actor
        self.status = TaskStatus.CLAIMED
        self.updated_at = datetime.utcnow()

    def start(self) -> None:
        if self.status == TaskStatus.CLAIMED:
            self.status = TaskStatus.RUNNING
            self.updated_at = datetime.utcnow()

    def succeed(self, output_artifacts: List[str], execution_result: Optional[Dict] = None) -> None:
        self.status = TaskStatus.SUCCEEDED
        self.output_artifacts = output_artifacts
        if execution_result:
            self.metadata["execution_result"] = execution_result
        self.updated_at = datetime.utcnow()

    def fail(self, error: str, retry: bool = False) -> None:
        self.status = TaskStatus.FAILED
        self.last_error = error
        self.retry_count += 1
        if retry and self.retry_count < self.max_retries:
            self.status = TaskStatus.RETRYING
        self.updated_at = datetime.utcnow()

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def block(self, reason: str) -> None:
        self.status = TaskStatus.BLOCKED
        self.last_error = f"Blocked: {reason}"
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.name,
            "dependency_status": self.dependency_status.name,
            "priority": self.priority.name,
            "workflow_id": self.workflow_id,
            "organization_id": self.organization_id,
            "dependencies": self.dependencies,
            "assigned_actor_id": self.assigned_actor.id if self.assigned_actor else None,
            "input_artifacts": self.input_artifacts,
            "output_artifacts": self.output_artifacts,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_error": self.last_error,
            "execution_parameters": self.execution_parameters,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "Task":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            status=TaskStatus[data.get("status", "PENDING")],
            dependency_status=DependencyStatus[data.get("dependency_status", "WAITING_FOR_DEPENDENCY")],
            priority=TaskPriority[data.get("priority", "MEDIUM")],
            workflow_id=data.get("workflow_id"),
            organization_id=data.get("organization_id"),
            dependencies=data.get("dependencies", []),
            input_artifacts=data.get("input_artifacts", []),
            output_artifacts=data.get("output_artifacts", []),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            last_error=data.get("last_error"),
            execution_parameters=data.get("execution_parameters", {}),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            **kwargs
        )
