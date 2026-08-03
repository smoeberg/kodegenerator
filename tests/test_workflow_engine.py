# tests/test_workflow_engine.py
import pytest
from domain.workflow import Workflow, WorkflowState, State, Transition
from domain.actor import Actor, ActorType
from domain.event import Event, EventType
from runtime.workflow_engine import WorkflowEngine
from runtime.event_bus import EventBus

@pytest.fixture
def sample_workflow():
    states = [
        State(id="new", name=WorkflowState.NEW),
        State(id="analysis", name=WorkflowState.ANALYSIS)
    ]
    transitions = [
        Transition(
            from_state="new",
            to_state="analysis",
            condition=None
        )
    ]
    workflow = Workflow(
        id="workflow_1",
        name="Feature Development",
        states=states,
        transitions=transitions
    )
    workflow.current_state = states[0]  # Sæt start-tilstand
    return workflow

@pytest.fixture
def sample_actor():
    return Actor(
        id="actor_1",
        type=ActorType.DIGITAL_EMPLOYEE,
        identity="GPT-5"
    )

@pytest.fixture
def workflow_engine():
    event_bus = EventBus()
    return WorkflowEngine(event_bus)

def test_start_workflow(sample_workflow, workflow_engine):
    assert workflow_engine.start_workflow(sample_workflow, sample_actor())
    assert sample_workflow.id in workflow_engine.workflows

def test_transition_workflow(sample_workflow, workflow_engine, sample_actor):
    workflow_engine.add_workflow(sample_workflow)
    assert workflow_engine.transition_workflow(
        "workflow_1",
        WorkflowState.ANALYSIS,
        sample_actor
    )
    assert workflow_engine.workflows["workflow_1"].current_state.name == WorkflowState.ANALYSIS
