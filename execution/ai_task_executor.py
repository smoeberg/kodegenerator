# execution/ai_task_executor.py
from typing import Dict, List, Optional, Any
from domain.task import Task, TaskStatus
from domain.artifact import Artifact, ArtifactType, ArtifactState
from domain.actor import Actor, ActorType
from domain.model import Model
from ai.client import AIClient
from runtime.model_registry import ModelRegistry
from runtime.artifact_lifecycle_manager import ArtifactLifecycleManager
from runtime.event_bus import EventBus
from domain.event import Event, EventType
import asyncio

class AITaskExecutor:
    """Udfører tasks ved at kalde LLM'er."""

    def __init__(
        self,
        model_registry: ModelRegistry,
        ai_client: AIClient,
        artifact_manager: ArtifactLifecycleManager,
        event_bus: EventBus
    ):
        self.model_registry = model_registry
        self.ai_client = ai_client
        self.artifact_manager = artifact_manager
        self.event_bus = event_bus

    async def execute(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """
        Udfør en Task ved at kalde en LLM.
        Returner et dictionary med resultater (f.eks. {"output": "genereret kode", "status": "success"}).
        """
        # Tjek om Actor er en Digital Employee med en model
        if actor.type != ActorType.DIGITAL_EMPLOYEE:
            return {"status": "failed", "error": "Actor is not a Digital Employee"}

        # Hent modellen for Actor
        model = self.model_registry.get_model(actor.identity)
        if not model:
            return {"status": "failed", "error": f"Model {actor.identity} not found"}

        # Bestem handling baseret på Task-navn
        if "generate" in task.name.lower() or "implement" in task.name.lower():
            return await self._execute_code_generation(task, actor, model)
        elif "review" in task.name.lower():
            return await self._execute_code_review(task, actor, model)
        elif "test" in task.name.lower():
            return await self._execute_test_generation(task, actor, model)
        elif "document" in task.name.lower():
            return await self._execute_documentation(task, actor, model)
        else:
            return await self._execute_generic(task, actor, model)

    async def _execute_code_generation(
        self,
        task: Task,
        actor: Actor,
        model: Model
    ) -> Dict[str, Any]:
        """Generér kode baseret på Task-beskrivelsen."""
        # Hent input-artefakter (f.eks. specifikationer)
        input_artifacts = []
        for artifact_id in task.input_artifacts:
            artifact = self.artifact_manager.artifacts.get(artifact_id)
            if artifact:
                input_artifacts.append(artifact)

        # Byg prompt
        prompt = f"""
        You are a {actor.role.name} with expertise in {', '.join(actor.role.capabilities)}.
        Your task is to: {task.description}

        Input artifacts:
        {self._format_artifacts(input_artifacts)}

        Generate the required code. Ensure it is:
        - Well-structured
        - Properly documented
        - Follows best practices
        - Handles edge cases
        """

        # Kald LLM
        try:
            output = await self.ai_client.generate(
                prompt=prompt,
                model_id=model.id,
                system_message="You are a senior software engineer. Generate high-quality code.",
                temperature=0.3,  # Lav temperatur for mere deterministisk output
                max_tokens=model.max_tokens
            )

            # Opret et nyt Artefakt med den genererede kode
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.IMPLEMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={
                    "code": output,
                    "language": "python",  # Antag Python (kan udvides)
                    "task_id": task.id
                }
            )

            # Log Event
            self.event_bus.publish(Event(
                id=f"event_{len(self.event_bus.events) + 1}",
                event_type=EventType.ARTIFACT_CREATED,
                actor=actor,
                artifact=artifact,
                timestamp=datetime.now(timezone.utc)
            ))

            return {
                "status": "success",
                "output": output,
                "artifact_id": artifact.id
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_code_review(
        self,
        task: Task,
        actor: Actor,
        model: Model
    ) -> Dict[str, Any]:
        """Review kode baseret på input-artefakter."""
        # Hent input-artefakter (f.eks. implementeringskode)
        input_artifacts = []
        for artifact_id in task.input_artifacts:
            artifact = self.artifact_manager.artifacts.get(artifact_id)
            if artifact:
                input_artifacts.append(artifact)

        if not input_artifacts:
            return {"status": "failed", "error": "No input artifacts for review"}

        # Byg prompt
        prompt = f"""
        You are a {actor.role.name} with expertise in code review.
        Your task is to: {task.description}

        Review the following code:
        {self._format_artifacts(input_artifacts)}

        Provide a detailed review including:
        - Code quality
        - Potential bugs
        - Performance issues
        - Security concerns
        - Suggestions for improvement

        Format your response as JSON:
        {{
            "feedback": "Your detailed feedback here",
            "score": 0-10,
            "issues": ["List of issues"],
            "suggestions": ["List of suggestions"]
        }}
        """

        # Kald LLM
        try:
            output = await self.ai_client.generate(
                prompt=prompt,
                model_id=model.id,
                system_message="You are a senior code reviewer. Provide thorough and constructive feedback.",
                temperature=0.2,  # Lav temperatur for mere konsistent output
                max_tokens=model.max_tokens
            )

            # Parse JSON (simplificeret)
            try:
                import json
                review_data = json.loads(output)
            except:
                review_data = {"feedback": output, "score": 8, "issues": [], "suggestions": []}

            # Opret et Review Artefakt
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.REVIEW,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={
                    "review": review_data,
                    "task_id": task.id
                }
            )

            # Log Event
            self.event_bus.publish(Event(
                id=f"event_{len(self.event_bus.events) + 1}",
                event_type=EventType.ARTIFACT_CREATED,
                actor=actor,
                artifact=artifact,
                timestamp=datetime.now(timezone.utc)
            ))

            return {
                "status": "success",
                "output": review_data,
                "artifact_id": artifact.id
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_test_generation(
        self,
        task: Task,
        actor: Actor,
        model: Model
    ) -> Dict[str, Any]:
        """Generér tests baseret på input-artefakter."""
        # Hent input-artefakter (f.eks. implementeringskode)
        input_artifacts = []
        for artifact_id in task.input_artifacts:
            artifact = self.artifact_manager.artifacts.get(artifact_id)
            if artifact:
                input_artifacts.append(artifact)

        if not input_artifacts:
            return {"status": "failed", "error": "No input artifacts for test generation"}

        # Byg prompt
        prompt = f"""
        You are a {actor.role.name} with expertise in testing.
        Your task is to: {task.description}

        Generate comprehensive tests for the following code:
        {self._format_artifacts(input_artifacts)}

        Include:
        - Unit tests
        - Integration tests
        - Edge case tests
        - Performance tests (if applicable)

        Format your response as Python code with pytest.
        """

        # Kald LLM
        try:
            output = await self.ai_client.generate(
                prompt=prompt,
                model_id=model.id,
                system_message="You are a senior test engineer. Generate thorough and effective tests.",
                temperature=0.3,
                max_tokens=model.max_tokens
            )

            # Opret et Test Artefakt
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.IMPLEMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={
                    "tests": output,
                    "task_id": task.id,
                    "coverage": 0.95  # Antag 95% dækning (kan beregnes senere)
                }
            )

            # Log Event
            self.event_bus.publish(Event(
                id=f"event_{len(self.event_bus.events) + 1}",
                event_type=EventType.ARTIFACT_CREATED,
                actor=actor,
                artifact=artifact,
                timestamp=datetime.now(timezone.utc)
            ))

            return {
                "status": "success",
                "output": output,
                "artifact_id": artifact.id
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_documentation(
        self,
        task: Task,
        actor: Actor,
        model: Model
    ) -> Dict[str, Any]:
        """Generér dokumentation baseret på input-artefakter."""
        # Hent input-artefakter (f.eks. kode, arkitektur)
        input_artifacts = []
        for artifact_id in task.input_artifacts:
            artifact = self.artifact_manager.artifacts.get(artifact_id)
            if artifact:
                input_artifacts.append(artifact)

        if not input_artifacts:
            return {"status": "failed", "error": "No input artifacts for documentation"}

        # Byg prompt
        prompt = f"""
        You are a {actor.role.name} with expertise in documentation.
        Your task is to: {task.description}

        Generate comprehensive documentation for the following:
        {self._format_artifacts(input_artifacts)}

        Include:
        - Overview
        - Installation instructions
        - Usage examples
        - API documentation (if applicable)
        - Architecture diagrams (as text)
        - Best practices
        - Troubleshooting

        Format your response as Markdown.
        """

        # Kald LLM
        try:
            output = await self.ai_client.generate(
                prompt=prompt,
                model_id=model.id,
                system_message="You are a senior technical writer. Generate clear and comprehensive documentation.",
                temperature=0.3,
                max_tokens=model.max_tokens
            )

            # Opret et Dokumentations Artefakt
            artifact = self.artifact_manager.create_artifact(
                artifact_type=ArtifactType.DOCUMENTATION,
                owner=actor,
                department_id=actor.department.id if actor.department else None,
                workflow_id=task.workflow_id,
                metadata={
                    "documentation": output,
                    "task_id": task.id
                }
            )

            # Log Event
            self.event_bus.publish(Event(
                id=f"event_{len(self.event_bus.events) + 1}",
                event_type=EventType.ARTIFACT_CREATED,
                actor=actor,
                artifact=artifact,
                timestamp=datetime.now(timezone.utc)
            ))

            return {
                "status": "success",
                "output": output,
                "artifact_id": artifact.id
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_generic(
        self,
        task: Task,
        actor: Actor,
        model: Model
    ) -> Dict[str, Any]:
        """Udfør en generisk Task (faldback)."""
        # Byg prompt
        prompt = f"""
        You are a {actor.role.name} with expertise in {', '.join(actor.role.capabilities)}.
        Your task is to: {task.description}

        Provide a detailed and thorough response.
        """

        # Kald LLM
        try:
            output = await self.ai_client.generate(
                prompt=prompt,
                model_id=model.id,
                system_message="You are a helpful assistant. Provide detailed and accurate responses.",
                temperature=0.7,
                max_tokens=model.max_tokens
            )

            return {
                "status": "success",
                "output": output
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    def _format_artifacts(self, artifacts: List[Artifact]) -> str:
        """Formater en liste af Artefakter til en prompt."""
        formatted = []
        for artifact in artifacts:
            if artifact.artifact_type == ArtifactType.IMPLEMENTATION:
                formatted.append(f"Code (Version {artifact.version}):\n{artifact.metadata.get('code', '')}")
            elif artifact.artifact_type == ArtifactType.ARCHITECTURE:
                formatted.append(f"Architecture (Version {artifact.version}):\n{artifact.metadata.get('adr', '')}")
            elif artifact.artifact_type == ArtifactType.REVIEW:
                formatted.append(f"Review (Version {artifact.version}):\n{artifact.metadata.get('review', '')}")
            else:
                formatted.append(f"Artifact {artifact.id} (Type: {artifact.artifact_type.value}):\n{artifact.metadata}")
        return "\n\n".join(formatted)
