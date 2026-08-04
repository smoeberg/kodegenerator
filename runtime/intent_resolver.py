
from typing import Dict, Optional
from domain.intent import Intent
from domain.actor import Actor
from domain.workflow import Workflow

class IntentResolver:
    """Ansvarlig for at parse Intents og mappe dem til det korrekte Workflow."""

    def __init__(self, workflows: Dict[str, Workflow]):
        self.workflows = workflows

    def resolve_intent(self, intent: Intent, actor: Actor) -> Optional[Workflow]:
        """Find det rette Workflow baseret på Intent."""
        for workflow in self.workflows.values():
            if not intent.goal or not workflow.name or intent.goal.lower() in workflow.name.lower():
                return workflow
        if self.workflows:
            return list(self.workflows.values())[0]
        return None

    def create_workflow_from_intent(self, intent: Intent, actor: Actor) -> Optional[Workflow]:
        """Opret et nyt Workflow instans ud fra en Intent."""
        workflow = self.resolve_intent(intent, actor)
        if workflow:
            import copy
            wf_copy = copy.deepcopy(workflow)
            wf_copy.intent = intent
            if not wf_copy.current_state and wf_copy.states:
                wf_copy.current_state = wf_copy.states[0]
            return wf_copy
        return None
