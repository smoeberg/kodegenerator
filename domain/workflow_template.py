# domain/workflow_template.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from .workflow import Workflow, WorkflowState, State, Transition, Gate
from .task import Task, TaskPriority

@dataclass
class WorkflowTemplate:
    """Skabelon for et Workflow, der kan instantieres med specifikke parametre."""
    id: str
    name: str
    description: str = ""
    required_capabilities: List[str] = field(default_factory=list)  # Liste af Capability-ID'er
    default_priority: TaskPriority = TaskPriority.MEDIUM
    states: List[State] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    gates: List[Gate] = field(default_factory=list)
    default_tasks: List[Dict] = field(default_factory=list)  # Liste af Task-definitioner
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def instantiate(
        self,
        workflow_id: str,
        intent_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        **kwargs
    ) -> Workflow:
        """Instantier WorkflowTemplate til et konkret Workflow."""
        # Opret States
        states = [
            State(
                id=f"{workflow_id}_{state.id}",
                name=state.name,
                description=state.description
            )
            for state in self.states
        ]

        # Opret Transitions
        transitions = [
            Transition(
                from_state=f"{workflow_id}_{transition.from_state}",
                to_state=f"{workflow_id}_{transition.to_state}",
                condition=transition.condition,
                gate=transition.gate
            )
            for transition in self.transitions
        ]

        # Opret Gates
        gates = [
            Gate(
                id=f"{workflow_id}_{gate.id}",
                name=gate.name,
                required_approvals=gate.required_approvals,
                min_consensus_score=gate.min_consensus_score,
                conditions=gate.conditions
            )
            for gate in self.gates
        ]

        # Opret Workflow
        workflow = Workflow(
            id=workflow_id,
            name=self.name,
            description=self.description,
            states=states,
            transitions=transitions,
            gates=gates,
            intent_id=intent_id,
            organization_id=organization_id
        )

        # Sæt start-tilstand
        workflow.current_state = next(
            (s for s in workflow.states if s.name == WorkflowState.NEW),
            None
        )

        # Opret default Tasks
        for task_def in self.default_tasks:
            task = Task(
                id=f"{workflow_id}_task_{task_def.get('id', 'default')}",
                name=task_def.get("name", "Unnamed Task"),
                description=task_def.get("description", ""),
                priority=task_def.get("priority", self.default_priority),
                workflow_id=workflow_id,
                dependencies=task_def.get("dependencies", []),
                metadata=task_def.get("metadata", {})
            )
            # Tilføj Task til Workflow (via WorkflowEngine)
            # (Vi gør dette senere, når vi integrerer med WorkflowEngine)
            workflow.metadata["default_tasks"] = workflow.metadata.get("default_tasks", []) + [task.to_dict()]

        return workflow
