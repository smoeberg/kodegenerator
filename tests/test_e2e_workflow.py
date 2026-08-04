from domain.organization import Organization
from domain.actor import Actor, ActorType
from domain.intent import Intent, IntentPriority
from domain.workflow import Workflow, WorkflowState, State, Transition, Gate
from domain.artifact import Artifact, ArtifactType, ArtifactState
from runtime.workflow_engine import WorkflowEngine
from runtime.event_bus import EventBus
from runtime.task_scheduler import TaskScheduler
from runtime.artifact_lifecycle_manager import ArtifactLifecycleManager

def test_e2e_workflow_execution():
    # 1. Setup Dependencies
    event_bus = EventBus()
    task_scheduler = TaskScheduler()
    artifact_manager = ArtifactLifecycleManager(event_bus=event_bus)

    # 2. Setup Organization & Actor
    org = Organization(id="org-1", name="EIRA Org")
    actor = Actor(id="actor-1", identity="Digital Dev", type=ActorType.DIGITAL_EMPLOYEE)

    # 3. Setup States
    s_new = State(id="s1", name=WorkflowState.NEW, description="New workflow")
    s_impl = State(id="s2", name=WorkflowState.IMPLEMENTATION, description="Implementation phase")
    s_rev = State(id="s3", name=WorkflowState.REVIEW, description="Review phase")
    s_appr = State(id="s4", name=WorkflowState.APPROVED, description="Approved phase")

    # 4. Setup Transitions
    transitions = [
        Transition(from_state=WorkflowState.NEW.value, to_state=WorkflowState.IMPLEMENTATION.value, condition="intent_id == 'intent-101'"),
        Transition(from_state=WorkflowState.IMPLEMENTATION.value, to_state=WorkflowState.REVIEW.value, condition="code_len > 10"),
        Transition(from_state=WorkflowState.REVIEW.value, to_state=WorkflowState.APPROVED.value, condition="score >= 80")
    ]

    workflow = Workflow(
        id="wf-1",
        name="Auth Workflow",
        states=[s_new, s_impl, s_rev, s_appr],
        transitions=transitions,
        current_state=s_new
    )

    # 5. Initialize Engine
    engine = WorkflowEngine(
        event_bus=event_bus,
        task_scheduler=task_scheduler,
        artifact_manager=artifact_manager
    )
    engine.add_workflow(workflow)

    # Provide testing context override
    current_context = {"intent_id": "intent-101"}
    engine._get_context = lambda actor, artifact: current_context

    # State Transition 1: NEW -> IMPLEMENTATION
    assert engine.transition_workflow("wf-1", WorkflowState.IMPLEMENTATION, actor=actor, artifact=None) is True
    assert workflow.current_state.name == WorkflowState.IMPLEMENTATION

    # Artifact creation
    content = "def authenticate(user, password):\n    return True"
    artifact = Artifact(
        id="art-1",
        version="1.0.0",
        artifact_type=ArtifactType.IMPLEMENTATION,
        hash=Artifact.calculate_hash(None, content)
    )

    # State Transition 2: IMPLEMENTATION -> REVIEW
    current_context = {"code_len": len(content)}
    assert engine.transition_workflow("wf-1", WorkflowState.REVIEW, actor=actor, artifact=artifact) is True
    assert workflow.current_state.name == WorkflowState.REVIEW

    # State Transition 3: REVIEW -> APPROVED
    current_context = {"score": 85}
    assert engine.transition_workflow("wf-1", WorkflowState.APPROVED, actor=actor, artifact=artifact) is True
    assert workflow.current_state.name == WorkflowState.APPROVED

    print("✅ E2E Workflow Execution Test Passed!")

if __name__ == "__main__":
    test_e2e_workflow_execution()
