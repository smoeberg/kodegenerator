# execution/task_executor_factory.py
"""Executor factory for DOR.

Two resolution modes are supported:
  * canonical (P3-14): ``get(task_type)`` — used by ``TaskExecutionService``,
    backed by the deterministic ``DictTaskExecutorFactory`` registry.
  * legacy actor-based: ``get_executor(actor)`` — kept for existing callers.
"""

from typing import Any

from domain.actor import Actor, ActorType
from execution.ai_task_executor import AITaskExecutor
from execution.human_task_executor import HumanTaskExecutor
from execution.service_task_executor import ServiceTaskExecutor
from execution.pipeline_executors import build_pipeline_executor_registry
from services.task_execution_service import DictTaskExecutorFactory


class TaskExecutorFactory:
    """Resolves the right executor for a task."""

    def __init__(
        self,
        ai_executor: AITaskExecutor,
        human_executor: HumanTaskExecutor,
        service_executor: ServiceTaskExecutor,
    ):
        self.ai_executor = ai_executor
        self.human_executor = human_executor
        self.service_executor = service_executor
        # Canonical registry (P3-14): used by TaskExecutionService.
        self._canonical = DictTaskExecutorFactory(
            executors=build_pipeline_executor_registry()
        )

    def get(self, task_type: str) -> Any:
        """Canonical P3-14 resolution by task type."""
        return self._canonical.get(task_type)

    def get_executor(self, actor: Actor) -> Any:
        """Legacy resolution by actor type."""
        if actor.type == ActorType.DIGITAL_EMPLOYEE:
            return self.ai_executor
        elif actor.type == ActorType.HUMAN:
            return self.human_executor
        elif actor.type == ActorType.SERVICE:
            return self.service_executor
        else:
            raise ValueError(f"No executor available for Actor type: {actor.type}")
