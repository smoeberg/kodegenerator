# execution/ai_task_executor.py
from datetime import datetime, timezone
from typing import Any

from ai.client import AIClient
from domain.actor import Actor, ActorType
from domain.artifact import Artifact, ArtifactType
from domain.event import Event, EventType
from domain.task import Task
from runtime.artifact_lifecycle_manager import ArtifactLifecycleManager
from runtime.event_bus import EventBus
from runtime.model_registry import Model, ModelRegistry


class AITaskExecutor:
    """Execute AI tasks through the explicit, provider-neutral AI boundary."""

    def __init__(
        self,
        model_registry: ModelRegistry,
        ai_client: AIClient,
        artifact_manager: ArtifactLifecycleManager,
        event_bus: EventBus,
    ):
        self.model_registry = model_registry
        self.ai_client = ai_client
        self.artifact_manager = artifact_manager
        self.event_bus = event_bus

    async def execute(self, task: Task, actor: Actor) -> dict[str, Any]:
        if actor.type != ActorType.DIGITAL_EMPLOYEE:
            return {"status": "failed", "error": "Actor is not a Digital Employee"}

        model = self.model_registry.get_model(actor.identity)
        if not model:
            return {"status": "failed", "error": f"Model {actor.identity} not found"}

        if "generate" in task.name.lower() or "implement" in task.name.lower():
            return await self._execute_code_generation(task, actor, model)
        if "review" in task.name.lower():
            return await self._execute_code_review(task, actor, model)
        if "test" in task.name.lower():
            return await self._execute_test_generation(task, actor, model)
        if "document" in task.name.lower():
            return await self._execute_documentation(task, actor, model)
        return await self._execute_generic(task, actor, model)

    async def _generate(
        self, *, model: Model, prompt: str, system_message: str, temperature: float
    ) -> str:
        """Call the canonical AI boundary; provider integration intentionally remains deferred."""
        return await self.ai_client.generate_response(
            model=model,
            prompt=prompt,
            system_message=system_message,
            temperature=temperature,
            max_tokens=model.max_tokens,
        )

    async def _execute_code_generation(
        self, task: Task, actor: Actor, model: Model
    ) -> dict[str, Any]:
        input_artifacts = [
            artifact
            for artifact_id in task.input_artifacts
            if (artifact := self.artifact_manager.artifacts.get(artifact_id))
        ]
        prompt = f"""
You are a {actor.role.name} with expertise in {", ".join(actor.role.capabilities)}.
Your task is to: {task.description}

Input artifacts:
{self._format_artifacts(input_artifacts)}

Generate the required code. Ensure it is well-structured, documented, robust, and handles edge cases.
"""
        try:
            output = await self._generate(
                model=model,
                prompt=prompt,
                system_message="You are a senior software engineer. Generate high-quality code.",
                temperature=0.3,
            )
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.IMPLEMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={"code": output, "language": "python", "task_id": task.id},
            )
            self.event_bus.publish(
                Event(
                    id=f"event_{len(self.event_bus.events) + 1}",
                    event_type=EventType.ARTIFACT_CREATED,
                    actor=actor,
                    artifact=artifact,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            return {"status": "success", "output": output, "artifact_id": artifact.id}
        except Exception as exc:  # noqa: BLE001 - provider boundary returns explicit failure
            return {"status": "failed", "error": str(exc)}

    async def _execute_code_review(
        self, task: Task, actor: Actor, model: Model
    ) -> dict[str, Any]:
        input_artifacts = [
            artifact
            for artifact_id in task.input_artifacts
            if (artifact := self.artifact_manager.artifacts.get(artifact_id))
        ]
        if not input_artifacts:
            return {"status": "failed", "error": "No input artifacts for review"}
        prompt = f"""
You are a senior code reviewer. Your task is to: {task.description}

Review the following code:
{self._format_artifacts(input_artifacts)}

Provide detailed feedback on quality, bugs, performance, security, and improvements.
"""
        try:
            output = await self._generate(
                model=model,
                prompt=prompt,
                system_message="You are a senior code reviewer. Provide thorough and constructive feedback.",
                temperature=0.2,
            )
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.REVIEW,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={"review": output, "task_id": task.id},
            )
            self.event_bus.publish(
                Event(
                    id=f"event_{len(self.event_bus.events) + 1}",
                    event_type=EventType.ARTIFACT_CREATED,
                    actor=actor,
                    artifact=artifact,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            return {"status": "success", "output": output, "artifact_id": artifact.id}
        except Exception as exc:  # noqa: BLE001 - provider boundary returns explicit failure
            return {"status": "failed", "error": str(exc)}

    async def _execute_test_generation(
        self, task: Task, actor: Actor, model: Model
    ) -> dict[str, Any]:
        input_artifacts = [
            artifact
            for artifact_id in task.input_artifacts
            if (artifact := self.artifact_manager.artifacts.get(artifact_id))
        ]
        if not input_artifacts:
            return {
                "status": "failed",
                "error": "No input artifacts for test generation",
            }
        prompt = f"Generate pytest tests for:\n{self._format_artifacts(input_artifacts)}\nTask: {task.description}"
        try:
            output = await self._generate(
                model=model,
                prompt=prompt,
                system_message="You are a senior test engineer. Generate thorough and effective tests.",
                temperature=0.3,
            )
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.IMPLEMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={"tests": output, "task_id": task.id},
            )
            return {"status": "success", "output": output, "artifact_id": artifact.id}
        except Exception as exc:  # noqa: BLE001 - provider boundary returns explicit failure
            return {"status": "failed", "error": str(exc)}

    async def _execute_documentation(
        self, task: Task, actor: Actor, model: Model
    ) -> dict[str, Any]:
        input_artifacts = [
            artifact
            for artifact_id in task.input_artifacts
            if (artifact := self.artifact_manager.artifacts.get(artifact_id))
        ]
        if not input_artifacts:
            return {"status": "failed", "error": "No input artifacts for documentation"}
        prompt = f"Generate Markdown documentation for:\n{self._format_artifacts(input_artifacts)}\nTask: {task.description}"
        try:
            output = await self._generate(
                model=model,
                prompt=prompt,
                system_message="You are a senior technical writer. Generate clear and comprehensive documentation.",
                temperature=0.3,
            )
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.DOCUMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={"documentation": output, "task_id": task.id},
            )
            return {"status": "success", "output": output, "artifact_id": artifact.id}
        except Exception as exc:  # noqa: BLE001 - provider boundary returns explicit failure
            return {"status": "failed", "error": str(exc)}

    async def _execute_generic(
        self, task: Task, actor: Actor, model: Model
    ) -> dict[str, Any]:
        prompt = f"You are a {actor.role.name}. Your task is to: {task.description}"
        try:
            output = await self._generate(
                model=model,
                prompt=prompt,
                system_message="You are a helpful assistant. Provide detailed and accurate responses.",
                temperature=0.7,
            )
            return {"status": "success", "output": output}
        except Exception as exc:  # noqa: BLE001 - provider boundary returns explicit failure
            return {"status": "failed", "error": str(exc)}

    def _format_artifacts(self, artifacts: list[Artifact]) -> str:
        formatted = []
        for artifact in artifacts:
            if artifact.artifact_type == ArtifactType.IMPLEMENTATION:
                formatted.append(
                    f"Code (Version {artifact.version}):\n{artifact.metadata.get('code', '')}"
                )
            elif artifact.artifact_type == ArtifactType.ARCHITECTURE:
                formatted.append(
                    f"Architecture (Version {artifact.version}):\n{artifact.metadata.get('adr', '')}"
                )
            elif artifact.artifact_type == ArtifactType.REVIEW:
                formatted.append(
                    f"Review (Version {artifact.version}):\n{artifact.metadata.get('review', '')}"
                )
            else:
                formatted.append(
                    f"Artifact {artifact.id} (Type: {artifact.artifact_type.value}):\n{artifact.metadata}"
                )
        return "\n\n".join(formatted)
