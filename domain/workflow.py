"""
Workflow Domain Model

Represents a process definition with states, transitions, and gates.
Workflows are the orchestration mechanism for executing Intents.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime, timezone
from enum import Enum, auto
import uuid

if TYPE_CHECKING:
    from domain.actor import Actor
    from domain.artifact import Artifact
    from domain.event import Event
    from domain.intent import Intent
    from domain.organization import Organization


class WorkflowState(Enum):
    """States for a Workflow."""
    NEW = auto()
    ANALYSIS = auto()
    DESIGN = auto()
    IMPLEMENTATION = auto()
    REVIEW = auto()
    APPROVED = auto()
    RELEASED = auto()
    REJECTED = auto()
    ARCHIVED = auto()


class WorkflowStatus(Enum):
    """Runtime status of a Workflow."""
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class State:
    """Represents a state in a Workflow's state machine."""
    id: str
    name: WorkflowState
    description: str = ""
    is_initial: bool = False
    is_final: bool = False


@dataclass
class Gate:
    """Represents a gate (condition) that must be satisfied to proceed in a Workflow."""
    id: str
    name: str
    description: str = ""
    required_approvals: List[str] = field(default_factory=list)
    min_consensus_score: float = 0.0
    conditions: Dict[str, Any] = field(default_factory=dict)
    decision_id: Optional[str] = None

    def is_satisfied(self, artifact: Optional["Artifact"], approvals: List[str]) -> bool:
        """Check if this gate is satisfied."""
        for required_role in self.required_approvals:
            if required_role not in approvals:
                return False
        if artifact and self.min_consensus_score > 0:
            if artifact.get_consensus_score() < self.min_consensus_score:
                return False
        if artifact:
            for key, value in self.conditions.items():
                if key == "test_coverage":
                    artifact_coverage = getattr(artifact, "test_coverage", 0.0)
                    if artifact_coverage < value:
                        return False
        return True


@dataclass
class Transition:
    """Represents a transition between states in a Workflow."""
    from_state: WorkflowState
    to_state: WorkflowState
    condition: Optional[str] = None
    gate_id: Optional[str] = None
    description: str = ""


@dataclass
class Workflow:
    """Represents a process definition with states, transitions, and gates."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    states: List[State] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    gates: List[Gate] = field(default_factory=list)
    current_state: Optional[State] = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    version: str = "1.0.0"

    organization: Optional["Organization"] = None
    intent: Optional["Intent"] = None
    tasks: List["Task"] = field(default_factory=list)
    artifacts: List["Artifact"] = field(default_factory=list)
    events: List["Event"] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not hasattr(self, "id") or self.id is None:
            object.__setattr__(self, "id", str(uuid.uuid4()))
        if not self.states:
            self.states = [
                State(id=f"{self.id}_new", name=WorkflowState.NEW, description="Workflow created, not yet started", is_initial=True),
                State(id=f"{self.id}_analysis", name=WorkflowState.ANALYSIS, description="Analyzing requirements"),
                State(id=f"{self.id}_design", name=WorkflowState.DESIGN, description="Designing solution"),
                State(id=f"{self.id}_implementation", name=WorkflowState.IMPLEMENTATION, description="Implementing solution"),
                State(id=f"{self.id}_review", name=WorkflowState.REVIEW, description="Reviewing outputs"),
                State(id=f"{self.id}_approved", name=WorkflowState.APPROVED, description="Approved and ready for release", is_final=True),
                State(id=f"{self.id}_released", name=WorkflowState.RELEASED, description="Released to production", is_final=True),
                State(id=f"{self.id}_rejected", name=WorkflowState.REJECTED, description="Rejected (can be resubmitted)"),
                State(id=f"{self.id}_archived", name=WorkflowState.ARCHIVED, description="Archived (read-only)", is_final=True),
            ]
            initial_states = [s for s in self.states if s.is_initial]
            if initial_states:
                self.current_state = initial_states[0]
        if not self.current_state and self.states:
            self.current_state = self.states[0]

    def add_state(self, state: State) -> None:
        if state not in self.states:
            self.states.append(state)

    def add_transition(self, transition: Transition) -> None:
        if transition not in self.transitions:
            self.transitions.append(transition)

    def add_gate(self, gate: Gate) -> None:
        if gate not in self.gates:
            self.gates.append(gate)

    def get_transition(self, from_state: WorkflowState, to_state: WorkflowState) -> Optional[Transition]:
        return next(
            (transition for transition in self.transitions if transition.from_state == from_state and transition.to_state == to_state),
            None,
        )

    def get_gate(self, gate_id: str) -> Optional[Gate]:
        return next((gate for gate in self.gates if gate.id == gate_id), None)

    def can_transition(self, new_state: WorkflowState, actor: "Actor", artifact: Optional["Artifact"] = None) -> bool:
        if not self.current_state:
            return new_state in [s.name for s in self.states if s.is_initial]
        transition = self.get_transition(self.current_state.name, new_state)
        if not transition:
            return False
        if transition.condition:
            from domain.condition_evaluator import ConditionEvaluator, ConditionEvaluationError
            try:
                context = self._get_condition_context(actor, artifact)
                if not ConditionEvaluator().evaluate(transition.condition, context):
                    return False
            except ConditionEvaluationError:
                return False
        if transition.gate_id:
            gate = self.get_gate(transition.gate_id)
            if gate:
                approvals = []
                if artifact:
                    approvals = [sig.role_id for sig in artifact.signatures if sig.status == "approved"]
                if not gate.is_satisfied(artifact, approvals):
                    return False
        return True

    def transition_to(
        self,
        new_state: WorkflowState,
        actor: "Actor",
        artifact: Optional["Artifact"] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> List["Event"]:
        """Validate a transition and return the domain events it produces.

        State mutation is deliberately performed by ``apply_event`` so the
        application layer can persist aggregate state and its event atomically.
        """
        if not self.can_transition(new_state, actor, artifact):
            raise InvalidTransitionError(
                f"Cannot transition from {self.current_state.name if self.current_state else 'None'} to {new_state}"
            )
        new_state_obj = next((s for s in self.states if s.name == new_state), None)
        if not new_state_obj:
            raise InvalidTransitionError(f"State {new_state} not found in Workflow")

        from domain.event import create_workflow_state_changed_event
        event = create_workflow_state_changed_event(
            workflow_id=self.id,
            new_state=new_state.name,
            organization_id=self.organization.id if self.organization else None,
            actor_id=actor.id,
            old_state=self.current_state.name.name if self.current_state else None,
            intent_id=self.intent.id if self.intent else None,
            artifact_id=artifact.id if artifact else None,
            evidence=evidence or {},
        )
        return [event]

    def apply_event(self, event: "Event") -> None:
        from domain.event import EventType
        if event.event_type != EventType.WORKFLOW_STATE_CHANGED:
            return
        new_state_name = event.metadata.get("new_state")
        new_state_obj = next(
            (state for state in self.states if state.name.name == new_state_name),
            None,
        )
        if new_state_obj is None:
            raise InvalidTransitionError(f"State {new_state_name} not found in Workflow")
        self.current_state = new_state_obj
        if new_state_obj.name in {WorkflowState.APPROVED, WorkflowState.RELEASED, WorkflowState.ARCHIVED}:
            self.status = WorkflowStatus.COMPLETED
        elif new_state_obj.name == WorkflowState.REJECTED:
            self.status = WorkflowStatus.FAILED
        else:
            self.status = WorkflowStatus.RUNNING
        self.updated_at = datetime.now(timezone.utc)

    def _get_condition_context(self, actor: "Actor", artifact: Optional["Artifact"]) -> Dict[str, Any]:
        context: Dict[str, Any] = {"actor": actor, "workflow": self, "artifact": artifact}
        if artifact:
            context.update({
                "test_coverage": getattr(artifact, "test_coverage", 0.0),
                "consensus_score": getattr(artifact, "consensus_score", 0.0),
                "artifact_type": artifact.artifact_type.value if hasattr(artifact, "artifact_type") else None,
            })
        return context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status.name,
            "current_state": self.current_state.name if self.current_state else None,
            "organization_id": self.organization.id if self.organization else None,
            "intent_id": self.intent.id if self.intent else None,
            "states": [{"id": s.id, "name": s.name.name, "description": s.description, "is_initial": s.is_initial, "is_final": s.is_final} for s in self.states],
            "transitions": [{"from_state": t.from_state.name, "to_state": t.to_state.name, "condition": t.condition, "gate_id": t.gate_id} for t in self.transitions],
            "gates": [{"id": g.id, "name": g.name, "required_approvals": g.required_approvals, "min_consensus_score": g.min_consensus_score, "conditions": g.conditions} for g in self.gates],
            "metadata": self.metadata,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "Workflow":
        states = [State(id=s["id"], name=WorkflowState[s["name"]], description=s.get("description", ""), is_initial=s.get("is_initial", False), is_final=s.get("is_final", False)) for s in data.get("states", [])]
        transitions = [Transition(from_state=WorkflowState[t["from_state"]], to_state=WorkflowState[t["to_state"]], condition=t.get("condition"), gate_id=t.get("gate_id"), description=t.get("description", "")) for t in data.get("transitions", [])]
        gates = [Gate(id=g["id"], name=g["name"], required_approvals=g.get("required_approvals", []), min_consensus_score=g.get("min_consensus_score", 0.0), conditions=g.get("conditions", {})) for g in data.get("gates", [])]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            status=WorkflowStatus[data.get("status", "PENDING")],
            states=states,
            transitions=transitions,
            gates=gates,
            metadata=data.get("metadata", {}),
            context=data.get("context", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(timezone.utc),
            **kwargs,
        )


class InvalidTransitionError(Exception):
    """Raised when a workflow transition violates its state machine."""
