# tests/test_intent_resolver.py
import pytest
from domain.intent import Intent, IntentPriority
from domain.actor import Actor, ActorType
from domain.role_definition import RoleDefinition
from domain.capability import Capability, CapabilityLevel
from runtime.intent_resolver import IntentResolver
from domain.workflow import Workflow, WorkflowState, State, Transition

@pytest.fixture
def sample_intent():
    return Intent(
        id="intent_1",
        goal="Implement OAuth2",
        priority=IntentPriority.HIGH,
        required_capabilities=["python", "oauth"]
    )

@pytest.fixture
def sample_actor():
    role = RoleDefinition(
        id="python_dev",
        name="Python Developer",
        capabilities=["python", "oauth"]
    )
    return Actor(
        id="actor_1",
        type=ActorType.DIGITAL_EMPLOYEE,
        identity="GPT-5",
        role=role
    )

@pytest.fixture
def sample_workflow():
    states = [
        State(id="new", name=WorkflowState.NEW),
        State(id="analysis", name=WorkflowState.ANALYSIS),
        State(id="design", name=WorkflowState.DESIGN)
    ]
    transitions = [
        Transition(
            from_state="new",
            to_state="analysis",
            condition=None
        )
    ]
    return Workflow(
        id="workflow_1",
        name="Feature Development",
        states=states,
        transitions=transitions
    )

def test_resolve_intent(sample_intent, sample_actor, sample_workflow):
    resolver = IntentResolver({"workflow_1": sample_workflow})
    workflow = resolver.resolve_intent(sample_intent, sample_actor)
    assert workflow is not None
    assert workflow.name == "Feature Development"

def test_create_workflow_from_intent(sample_intent, sample_actor, sample_workflow):
    resolver = IntentResolver({"workflow_1": sample_workflow})
    workflow = resolver.create_workflow_from_intent(sample_intent, sample_actor)
    assert workflow is not None
    assert workflow.current_state.name == WorkflowState.NEW
