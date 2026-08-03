# execution/task_executor_factory.py
from typing import Dict, Any
from domain.task import Task
from domain.actor import Actor, ActorType
from execution.ai_task_executor import AITaskExecutor
from execution.human_task_executor import HumanTaskExecutor
from execution.service_task_executor import ServiceTaskExecutor

class TaskExecutorFactory:
    """Fabrik til at oprette den rette Task Executor baseret på Actor-typen."""

    def __init__(
        self,
        ai_executor: AITaskExecutor,
        human_executor: HumanTaskExecutor,
        service_executor: ServiceTaskExecutor
    ):
        self.ai_executor = ai_executor
        self.human_executor = human_executor
        self.service_executor = service_executor

    def get_executor(self, actor: Actor) -> Any:
        """Hent den rette Task Executor for en Actor."""
        if actor.type == ActorType.DIGITAL_EMPLOYEE:
            return self.ai_executor
        elif actor.type == ActorType.HUMAN:
            return self.human_executor
        elif actor.type == ActorType.SERVICE:
            return self.service_executor
        else:
            raise ValueError(f"No executor available for Actor type: {actor.type}")
