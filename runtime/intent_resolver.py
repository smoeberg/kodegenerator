# runtime/intent_resolver.py
from typing import Dict, List, Optional
from domain.intent import Intent
from domain.workflow import Workflow, WorkflowState
from domain.actor import Actor
from domain.artifact import Artifact

class IntentResolver:
    """Oversætter Intents til Workflows baseret på Actor's Capabilities."""

    def __init__(self, workflows: Dict[str, Workflow]):
        self.workflows = workflows  # Dictionary af workflows (ID → Workflow)

    def resolve_intent(self, intent: Intent, actor: Actor) -> Optional[Workflow]:
        """Find det bedste Workflow for en given Intent og Actor."""
        # 1. Tjek om Actor kan håndtere Intent (baseret på Capabilities)
        if not intent.matches_actor(actor):
            return None

        # 2. Find workflows, der matcher Intent's goal
        matching_workflows = [
            wf for wf in self.workflows.values()
            if wf.name.lower() in intent.goal.lower()
        ]

        if not matching_workflows:
            return None

        # 3. Vælg det bedste workflow (simplificeret: første match)
        return matching_workflows[0]

    def create_workflow_from_intent(self, intent: Intent, actor: Actor) -> Optional[Workflow]:
        """Opret et nyt Workflow ud fra en Intent."""
        workflow = self.resolve_intent(intent, actor)
        if not workflow:
            return None

        # Opret en ny instans af Workflow
        new_workflow = Workflow(
            id=f"{intent.id}_workflow",
            name=workflow.name,
            description=workflow.description,
            states=workflow.states.copy(),
            transitions=workflow.transitions.copy(),
            gates=workflow.gates.copy(),
            intent=intent,
            organization=intent.organization
        )

        # Sæt start-tilstand
        new_workflow.current_state = next(
            (s for s in new_workflow.states if s.name == WorkflowState.NEW),
            None
        )

        return new_workflow
