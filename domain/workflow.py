# domain/workflow.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum, auto

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
    condition: Optional[str] = None  # Betingelse (f.eks. "test_coverage > 0.9")
    gate: Optional[str] = None  # Gate (f.eks. "SecurityBoard approval")

@dataclass
class Gate:
    """En gate (betingelse), der skal opfyldes for at fortsætte i Workflow."""
    id: str
    name: str
    required_approvals: List[str] = field(default_factory=list)  # Liste af RolleDefinition-ID'er
    min_consensus_score: float = 0.0
    conditions: Dict[str, any] = field(default_factory=dict)  # f.eks. {"test_coverage": 0.9}

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

    # Relationer
    organization: Optional["Organization"] = None
    intent: Optional["Intent"] = None
    artifacts: List["Artifact"] = field(default_factory=list)
    events: List["Event"] = field(default_factory=list)

    def add_state(self, state: State) -> None:
        """Tilføj en tilstand til Workflow."""
        if state not in self.states:
            self.states.append(state)

    def add_transition(self, transition: Transition) -> None:
        """Tilføj en overgang til Workflow."""
        if transition not in self.transitions:
            self.transitions.append(transition)

    def add_gate(self, gate: Gate) -> None:
        """Tilføj en gate til Workflow."""
        if gate not in self.gates:
            self.gates.append(gate)

    def transition_to(self, new_state_name: WorkflowState, actor: "Actor", artifact: Optional["Artifact"] = None) -> bool:
        """Forsøg at skifte til en ny tilstand (hvis betingelserne er opfyldt)."""
        # Find den nuværende tilstand
        current_state = self.current_state
        if not current_state:
            if new_state_name == WorkflowState.NEW:
                self.current_state = State(id=f"{self.id}_new", name=WorkflowState.NEW)
                return True
            return False

        # Find overgangen
        transition = next(
            (t for t in self.transitions
             if t.from_state == current_state.name.value and t.to_state == new_state_name.value),
            None
        )
        if not transition:
            return False

        # Tjek betingelsen (hvis den findes)
        if transition.condition:
            # Evaluer betingelsen (simplificeret: antag, at den er en Python-udtryk)
            try:
                if not eval(transition.condition, {}, self._get_context(actor, artifact)):
                    return False
            except:
                return False

        # Tjek gate (hvis den findes)
        if transition.gate:
            gate = next((g for g in self.gates if g.id == transition.gate), None)
            if gate and not self._check_gate(gate, actor, artifact):
                return False

        # Skift tilstand
        new_state = next((s for s in self.states if s.name == new_state_name), None)
        if new_state:
            self.current_state = new_state
            return True
        return False

    def _get_context(self, actor: "Actor", artifact: Optional["Artifact"]) -> Dict:
        """Hent kontekst for evaluering af betingelser."""
        context = {
            "actor": actor,
            "artifact": artifact,
            "workflow": self
        }
        if artifact:
            context.update({
                "test_coverage": getattr(artifact, "test_coverage", 0.0),
                "consensus_score": getattr(artifact, "consensus_score", 0.0)
            })
        return context

    def _check_gate(self, gate: Gate, actor: "Actor", artifact: Optional["Artifact"]) -> bool:
        """Tjek om en gate er opfyldt."""
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
