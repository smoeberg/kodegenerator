# runtime/task_scheduler.py
from typing import Dict, List, Optional
from queue import PriorityQueue
from domain.task import Task, TaskStatus, TaskPriority
from domain.actor import Actor
from domain.task_registry import TaskRegistry
from domain.workflow import Workflow
import heapq

class TaskScheduler:
    """Planlægger og prioriterer Tasks baseret på prioritet og afhængigheder."""

    def __init__(self, task_registry: Optional[TaskRegistry] = None):
        self.task_registry = task_registry
        self.queue: List[Task] = []  # Prioritets-kø (baseret på TaskPriority)

    def schedule_task(self, task: Task) -> None:
        """Planlæg en Task (tilføj til køen)."""
        # Prioriter baseret på TaskPriority (højere prioritet kommer først)
        heapq.heappush(self.queue, (task.priority.value, task.created_at.timestamp(), task))

    def get_next_task(self) -> Optional[Task]:
        """Hent den næste Task, der skal udføres."""
        while self.queue:
            _, _, task = heapq.heappop(self.queue)
            if task.status == TaskStatus.PENDING and task.can_start(self.task_registry.completed_tasks):
                return task
            # Hvis Tasken ikke kan startes, læg den tilbage i køen
            heapq.heappush(self.queue, (task.priority.value, task.created_at.timestamp(), task))
        return None

    def assign_task(self, task: Task, actor: Actor) -> bool:
        """Tildel en Task til en Actor."""
        if task.status != TaskStatus.PENDING:
            return False
        task.assign_to(actor)
        self.task_registry.add_task(task)
        return True

    def complete_task(self, task_id: str, output_artifacts: List[str]) -> None:
        """Markér en Task som færdiggjort."""
        task = self.task_registry.get_task(task_id)
        if task:
            task.complete(output_artifacts)
            self.task_registry.mark_task_completed(task_id)
