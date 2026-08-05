from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import InvalidTransitionError, WorkflowState
from runtime.core import DORRuntime, NotFoundError


def _runtime(tmp_path: Path) -> DORRuntime:
    return DORRuntime(f"sqlite:///{tmp_path / 'phase1.db'}")


def _context(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"):
    organization = Organization(id=organization_id, name=organization_id)
    actor = Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id)
    runtime.create_organization(organization)
    runtime.register_actor(actor, organization_id)
    principal = Principal(id=f"principal-{actor_id}", type="user")
    return runtime.establish_context(principal, organization_id, actor_id)


def test_runtime_boots_from_empty_database(tmp_path: Path):
    database = tmp_path / "empty.db"
    assert not database.exists()

    runtime = DORRuntime(f"sqlite:///{database}")
    runtime.boot()

    assert runtime.ready is True
    assert database.exists()


def test_organization_isolation(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.boot()

    context_a = _context(runtime, "org-a", "actor-a")
    organization_b = Organization(id="org-b", name="org-b")
    actor_b = Actor(id="actor-b", type=ActorType.HUMAN, identity="actor-b")
    runtime.create_organization(organization_b)
    runtime.register_actor(actor_b, "org-b")
    context_b = runtime.establish_context(Principal(id="principal-b", type="user"), "org-b", "actor-b")

    workflow_b = runtime.create_workflow(context_b, "private-b")

    with pytest.raises(NotFoundError):
        runtime.get_workflow(context_a, workflow_b.id)


def test_workflow_state_transitions(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "phase1")

    assert workflow.current_state.name == WorkflowState.NEW

    updated = runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)
    assert updated.current_state.name == WorkflowState.ANALYSIS

    with pytest.raises(InvalidTransitionError):
        runtime.transition_workflow(context, workflow.id, WorkflowState.RELEASED)


def test_event_durability(tmp_path: Path):
    database = tmp_path / "durable.db"
    runtime = DORRuntime(f"sqlite:///{database}")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "durable")
    runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)

    before_restart = runtime.get_events(context, workflow.id)
    assert [event.event_type.name for event in before_restart] == [
        "WORKFLOW_CREATED",
        "WORKFLOW_STATE_CHANGED",
    ]
    assert [event.sequence for event in before_restart] == [1, 2]

    restarted = DORRuntime(f"sqlite:///{database}")
    restarted.boot()
    restarted_context = restarted.establish_context(
        Principal(id="principal-actor-a", type="user"), "org-a", "actor-a"
    )
    after_restart = restarted.get_events(restarted_context, workflow.id)

    assert [event.id for event in after_restart] == [event.id for event in before_restart]
    assert [event.sequence for event in after_restart] == [1, 2]
    assert restarted.get_workflow(restarted_context, workflow.id).current_state.name == WorkflowState.ANALYSIS
