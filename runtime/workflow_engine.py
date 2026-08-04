# runtime/workflow_engine.py (Udvidet)
from typing import Dict, List, Optional
from domain.workflow import Workflow, WorkflowState, State, Transition, Gate
from domain.task import Task, TaskStatus, TaskPriority
from domain.artifact import Artifact, ArtifactState
from domain.actor import Actor
from domain.event import Event, EventType
from runtime.event_bus import EventBus
from runtime.task_scheduler import TaskScheduler
from runtime.artifact_lifecycle_manager import ArtifactLifecycleManager

class WorkflowEngine:
    """Udfører Workflows, håndterer Tasks og Gates."""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        task_scheduler: Optional[TaskScheduler] = None,
        artifact_manager: Optional[ArtifactLifecycleManager] = None
    ):
        self.event_bus = event_bus or EventBus()
        self.task_scheduler = task_scheduler or TaskScheduler()
        self.artifact_manager = artifact_manager or ArtifactLifecycleManager(event_bus=self.event_bus)
        self.workflows: Dict[str, Workflow] = {}
        self.workflow_tasks: Dict[str, List[Task]] = {}  # workflow_id → Liste af Tasks

    def add_workflow(self, workflow: Workflow) -> None:
        """Tilføj et Workflow til engine."""
        self.workflows[workflow.id] = workflow
        self.workflow_tasks[workflow.id] = []

    def start_workflow(self, workflow: Workflow, actor: Actor) -> bool:
        """Start et Workflow og opret indledende Tasks."""
        if workflow.id in self.workflows:
            return False

        workflow.current_state = next(
            (s for s in workflow.states if s.name == WorkflowState.NEW),
            None
        )
        if not workflow.current_state:
            return False

        self.workflows[workflow.id] = workflow
        self.workflow_tasks[workflow.id] = []

        # Opret indledende Tasks (f.eks. "Analyse Intent")
        initial_task = Task(
            id=f"{workflow.id}_task_1",
            name="Analyse Intent",
            workflow_id=workflow.id,
            dependencies=[],
            priority=TaskPriority.HIGH
        )
        self.workflow_tasks[workflow.id].append(initial_task)
        self.task_scheduler.schedule_task(initial_task)

        self._emit_event(
            EventType.WORKFLOW_STARTED,
            actor=actor,
            workflow=workflow
        )
        return True

    def transition_workflow(
        self,
        workflow_id: str,
        new_state: WorkflowState,
        actor: Actor,
        artifact: Optional[Artifact] = None
    ) -> bool:
        """Skift tilstand for et Workflow (med tjek af Gates)."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False

        # Find den nuværende tilstand
        current_state = workflow.current_state
        if not current_state:
            return False

        # Find overgangen (robust string/enum comparison)
        def _match_state(state_val, candidate):
            if state_val is None or candidate is None:
                return False
            s_str = str(state_val).lower()
            c_val = candidate.value if hasattr(candidate, 'value') else candidate
            c_str = str(c_val).lower()
            c_name = candidate.name.lower() if hasattr(candidate, 'name') else ''
            return s_str in [c_str, c_name, str(candidate).lower()]

        transition = next(
            (t for t in workflow.transitions
             if _match_state(t.from_state, current_state.name) and _match_state(t.to_state, new_state)),
            None
        )
        if not transition:
            return False

        # Tjek betingelsen (hvis den findes)
        if transition.condition:
            try:
                from domain.condition_evaluator import ConditionEvaluator
                evaluator = ConditionEvaluator()
                if not evaluator.evaluate(transition.condition, self._get_context(actor, artifact)):
                    return False
            except:
                return False

        # Tjek Gate (hvis den findes)
        if transition.gate:
            gate = next((g for g in workflow.gates if g.id == transition.gate), None)
            if gate and not self._check_gate(gate, actor, artifact):
                return False

        # Skift tilstand
        new_state_obj = next((s for s in workflow.states if s.name == new_state), None)
        if new_state_obj:
            workflow.current_state = new_state_obj
            self._emit_event(
                EventType.STATE_CHANGED,
                actor=actor,
                workflow=workflow,
                metadata={
                    "old_state": current_state.name.value,
                    "new_state": new_state.value
                }
            )

            # Opret nye Tasks baseret på den nye tilstand
            self._create_tasks_for_state(workflow, new_state)
            return True
        return False

    def _create_tasks_for_state(self, workflow: Workflow, state: WorkflowState) -> None:
        """Opret nye Tasks baseret på den aktuelle tilstand."""
        # Simplificeret: Opret en Task pr. tilstand (i praksis ville dette være mere dynamisk)
        task_id = f"{workflow.id}_task_{len(self.workflow_tasks[workflow.id]) + 1}"
        task = Task(
            id=task_id,
            name=f"Handle {state.name.value if hasattr(state.name, 'value') else str(state.name)}",
            workflow_id=workflow.id,
            dependencies=[t.id for t in self.workflow_tasks[workflow.id] if t.status == TaskStatus.COMPLETED],
            priority=TaskPriority.MEDIUM
        )
        self.workflow_tasks[workflow.id].append(task)
        self.task_scheduler.schedule_task(task)

    def _get_context(self, actor: Actor, artifact: Optional[Artifact]) -> Dict:
        """Hent kontekst for evaluering af betingelser."""
        context = {
            "actor": actor,
            "workflow": self.workflows.get(artifact.workflow_id) if artifact else None,
            "artifact": artifact
        }
        if artifact:
            context.update({
                "test_coverage": getattr(artifact, "test_coverage", 0.0),
                "consensus_score": getattr(artifact, "consensus_score", 0.0)
            })
        return context

    def _check_gate(self, gate: Gate, actor: Actor, artifact: Optional[Artifact]) -> bool:
        """Tjek om en Gate er opfyldt."""
        # Tjek required_approvals
        if artifact:
            for required_approval in gate.required_approvals:
                if not any(
                    sig["role_id"] == required_approval and sig["status"] == "approved"
                    for sig in artifact.signatures
                ):
                    return False
            # Tjek min_consensus_score
            if gate.min_consensus_score > getattr(artifact, "consensus_score", 0.0):
                return False
            # Tjek conditions
            for key, value in gate.conditions.items():
                if key == "test_coverage" and getattr(artifact, "test_coverage", 0.0) < value:
                    return False
        return True

    def _emit_event(self, event_type: EventType, **kwargs) -> None:
        """Udsend et Event via EventBus."""
        event = Event(
            id=f"event_{len(self.event_bus.events) + 1}",
            event_type=event_type,
            **kwargs
        )
        self.event_bus.publish(event)
