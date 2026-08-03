# domain/workflow.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum, auto

from domain.condition_evaluator import ConditionEvaluationError, ConditionEvaluator


class WorkflowState(Enum):
    """Tilstande for et Workflow."""
    NEW = auto()
    ANALYSIS = auto()
    DESIGN = auto()
    IMPLEMENTATION = auto()
    REVIEW = auto()
    APPROVED = auto()
    RELEASED = auto()
    REJECTED = auto()
    ARCHIVED = auto()


@dataclass
class State:
    """En tilstand i et Workflow."""
    id: str
    name: WorkflowState
    description: str = ""


@dataclass
class Transition:
    """En overgang mellem tilstande i et Workflow."""
    from_state: str
    to_state: str
    condition: Optional[str] = None
    gate: Optional[str] = None


@dataclass
class Gate:
    """En gate (betingelse), der skal opfyldes for at fortsætte i Workflow."""
    id: str
    name: str
    required_approvals: List[str] = field(default_factory=list)
    min_consensus_score: float = 0.0
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    """Repræsenterer en procesdefinition (states, transitions, gates)."""
    id: str
    name: str
    description: str = ""
    states: List[State] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    gates: List[Gate] = field(default_factory=list)
    current_state: Optional[State] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    organization: Optional["Organization"] = None
    intent: Optional["Intent"] = None
    artifacts: List["Artifact"] = field(default_factory=list)
    events: List["Event"] = field(default_factory=list)

    def add_state(self, state: State) -> None:
        if state not in self.states:
            self.states.append(state)

    def add_transition(self, transition: Transition) -> None:
        if transition not in self.transitions:
            self.transitions.append(transition)

    def add_gate(self, gate: Gate) -> None:
        if gate not in self.gates:
            self.gates.append(gate)

    def transition_to(
        self,
        new_state_name: WorkflowState,
        actor: "Actor",
        artifact: Optional["Artifact"] = None,
    ) -> bool:
        """Forsøg at skifte til en ny tilstand uden at udføre vilkårlig kode."""
        current_state = self.current_state
        if not current_state:
            if new_state_name == WorkflowState.NEW:
                self.current_state = State(id=f"{self.id}_new", name=WorkflowState.NEW)
                self.updated_at = datetime.now()
                return True
            return False

        transition = next(
            (
                t for t in self.transitions
                if t.from_state == current_state.name.value
                and t.to_state == new_state_name.value
            ),
            None,
        )
        if not transition:
            return False

        if transition.condition:
            try:
                if not ConditionEvaluator().evaluate(
                    transition.condition,
                    self._get_context(actor, artifact),
                ):
                    return False
            except ConditionEvaluationError:
                return False

        if transition.gate:
            gate = next((g for g in self.gates if g.id == transition.gate), None)
            if gate is None or not self._check_gate(gate, actor, artifact):
                return False

        new_state = next((s for s in self.states if s.name == new_state_name), None)
        if not new_state:
            return False

        self.current_state = new_state
        self.updated_at = datetime.now()
        return True

    def _get_context(self, actor: "Actor", artifact: Optional["Artifact"]) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "actor": actor,
            "artifact": artifact,
            "workflow": self,
        }
        if artifact:
            context.update({
                "test_coverage": getattr(artifact, "test_coverage", 0.0),
                "consensus_score": getattr(artifact, "consensus_score", 0.0),
            })
        return context

    def _check_gate(self, gate: Gate, actor: "Actor", artifact: Optional["Artifact"]) -> bool:
        if artifact:
            for required_approval in gate.required_approvals:
                if not any(
                    sig["role_id"] == required_approval and sig["status"] == "approved"
                    for sig in artifact.signatures
                ):
                    return False
            if gate.min_consensus_score > getattr(artifact, "consensus_score", 0.0):
                return False
            for key, value in gate.conditions.items():
                if key == "test_coverage" and getattr(artifact, "test_coverage", 0.0) < value:
                    return False
        return True
