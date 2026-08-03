# runtime/dor_runtime.py
from typing import Dict, List, Optional
from domain.organization import Organization
from domain.actor import Actor
from domain.intent import Intent
from domain.workflow import Workflow
from domain.artifact import Artifact
from domain.event import Event, EventType
from runtime.event_bus import EventBus
from runtime.intent_resolver import IntentResolver
from runtime.workflow_engine import WorkflowEngine
from runtime.task_scheduler import TaskScheduler
from runtime.policy_engine import PolicyEngine
from runtime.artifact_lifecycle_manager import ArtifactLifecycleManager
from runtime.capability_registry import CapabilityRegistry
from runtime.governance_engine import GovernanceEngine

class DORRuntime:
    """Hoved-Runtime for Digital Organization Runtime (DOR)."""

    def __init__(self, organization: Organization):
        self.organization = organization
        self.event_bus = EventBus()
        self.intent_resolver = IntentResolver({})
        self.workflow_engine = WorkflowEngine(
            self.event_bus,
            TaskScheduler(),
            ArtifactLifecycleManager(self.event_bus)
        )
        self.policy_engine = PolicyEngine([])
        self.capability_registry = CapabilityRegistry()
        self.governance_engine = GovernanceEngine(
            organization.governance,
            self.event_bus
        )

        # Registrer alle Actors fra organisationen
        for actor in organization.actors:
            self.capability_registry.actor_capabilities[actor.id] = [
                cap.id for cap in actor.capabilities
            ]

        # Abonner på Events
        self._setup_event_subscribers()

    def _setup_event_subscribers(self) -> None:
        """Opsæt event-subscribers."""
        self.event_bus.subscribe(
            EventType.WORKFLOW_STARTED,
            self._on_workflow_started
        )
        self.event_bus.subscribe(
            EventType.ARTIFACT_APPROVED,
            self._on_artifact_approved
        )
        self.event_bus.subscribe(
            EventType.ARTIFACT_REJECTED,
            self._on_artifact_rejected
        )

    def submit_intent(self, intent: Intent, actor: Actor) -> Optional[Workflow]:
        """Indsend en Intent og start det tilhørende Workflow."""
        # 1. Tjek om Actor kan håndtere Intent
        if not intent.matches_actor(actor):
            return None

        # 2. Resolv Intent til Workflow
        workflow = self.intent_resolver.resolve_intent(intent, actor)
        if not workflow:
            return None

        # 3. Opret et nyt Workflow
        new_workflow = self.intent_resolver.create_workflow_from_intent(intent, actor)
        if not new_workflow:
            return None

        # 4. Start Workflow
        if self.workflow_engine.start_workflow(new_workflow, actor):
            return new_workflow
        return None

    def _on_workflow_started(self, event: Event) -> None:
        """Håndter WORKFLOW_STARTED Event."""
        print(f"Workflow started: {event.workflow.id}")

    def _on_artifact_approved(self, event: Event) -> None:
        """Håndter ARTIFACT_APPROVED Event."""
        print(f"Artifact approved: {event.artifact.id}")

    def _on_artifact_rejected(self, event: Event) -> None:
        """Håndter ARTIFACT_REJECTED Event."""
        print(f"Artifact rejected: {event.artifact.id} (Reason: {event.metadata.get('reason', 'N/A')})")

    def add_workflow_template(self, workflow: Workflow) -> None:
        """Tilføj en Workflow-skabelon til IntentResolver."""
        self.intent_resolver.workflows[workflow.id] = workflow

    def add_policy(self, policy: "Policy") -> None:
        """Tilføj en Policy til PolicyEngine."""
        self.policy_engine.policies.append(policy)

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Hent et Artefakt."""
        return self.workflow_engine.artifact_manager.artifacts.get(artifact_id)
