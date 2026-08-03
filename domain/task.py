# domain/task.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

class TaskStatus(Enum):
    """Tilstande for en Task."""
    PENDING = auto()       # Venter på at blive startet
    ASSIGNED = auto()      # Tildelt til en Actor
    IN_PROGRESS = auto()   # I gang
    BLOCKED = auto()       # Blokeret (venter på afhængigheder)
    COMPLETED = auto()      # Færdiggjort
    FAILED = auto()        # Fejlet
    CANCELLED = auto()     # Annulleret

class TaskPriority(Enum):
    """Prioritetsniveauer for Tasks."""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

@dataclass
class Task:
    """Repræsenterer en opgave, der skal udføres i et Workflow."""
    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    workflow_id: Optional[str] = None  # Hvilket Workflow tilhører Tasken?
    assigned_actor: Optional["Actor"] = None  # Hvilken Actor er tildelt?
    dependencies: List[str] = field(default_factory=list)  # Liste af Task-ID'er, der skal færdiggøres først
    input_artifacts: List[str] = field(default_factory=list)  # Liste af Artefakt-ID'er (input)
    output_artifacts: List[str] = field(default_factory=list)  # Liste af Artefakt-ID'er (output)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)  # Yderligere data (f.eks. deadline, estimeret tid)

    def can_start(self, completed_tasks: List[str]) -> bool:
        """Tjek om Tasken kan startes (alle afhængigheder er færdige)."""
        return all(dep_id in completed_tasks for dep_id in self.dependencies)

    def is_blocked(self, completed_tasks: List[str]) -> bool:
        """Tjek om Tasken er blokeret (venter på afhængigheder)."""
        return not self.can_start(completed_tasks)

    def assign_to(self, actor: "Actor") -> None:
        """Tildel Tasken til en Actor."""
        self.assigned_actor = actor
        self.status = TaskStatus.ASSIGNED
        self.updated_at = datetime.now()

    def start(self) -> None:
        """Start Tasken."""
        if self.status == TaskStatus.ASSIGNED:
            self.status = TaskStatus.IN_PROGRESS
            self.updated_at = datetime.now()

    def complete(self, output_artifacts: List[str]) -> None:
        """Færdiggør Tasken."""
        self.status = TaskStatus.COMPLETED
        self.output_artifacts = output_artifacts
        self.updated_at = datetime.now()

    def fail(self, reason: str) -> None:
        """Markér Tasken som fejlet."""
        self.status = TaskStatus.FAILED
        self.metadata["failure_reason"] = reason
        self.updated_at = datetime.now()
