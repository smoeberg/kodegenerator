# domain/task_registry.py
from typing import Dict, List, Optional
from domain.task import Task, TaskStatus

class TaskRegistry:
    """Central registrering af alle Tasks."""

    def __init__(self):
        self.tasks: Dict[str, Task] = {}  # task_id → Task
        self.completed_tasks: List[str] = []  # Liste af færdiggjorte Task-ID'er

    def add_task(self, task: Task) -> None:
        """Tilføj en Task til registret."""
        if task.id not in self.tasks:
            self.tasks[task.id] = task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Hent en Task ud fra ID."""
        return self.tasks.get(task_id)

    def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Hent alle Tasks for et bestemt Workflow."""
        return [task for task in self.tasks.values() if task.workflow_id == workflow_id]

    def get_pending_tasks(self) -> List[Task]:
        """Hent alle Tasks, der er PENDING."""
        return [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]

    def get_assigned_tasks(self, actor_id: str) -> List[Task]:
        """Hent alle Tasks, der er tildelt til en bestemt Actor."""
        return [task for task in self.tasks.values()
                if task.assigned_actor and task.assigned_actor.id == actor_id]

    def get_blocked_tasks(self) -> List[Task]:
        """Hent alle Tasks, der er BLOCKED."""
        return [task for task in self.tasks.values()
                if task.status == TaskStatus.BLOCKED or task.is_blocked(self.completed_tasks)]

    def mark_task_completed(self, task_id: str) -> None:
        """Markér en Task som færdiggjort."""
        if task_id in self.tasks:
            self.completed_tasks.append(task_id)
