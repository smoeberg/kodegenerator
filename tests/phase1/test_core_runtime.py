"""Phase 1 acceptance tests for the DOR core runtime.

The suite exercises the public runtime boundary and deliberately avoids
persistence implementation details. These are the four Phase 1 gates:
boot, organization isolation, workflow transitions, and durable events.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import InvalidTransitionError, WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError


def _runtime(tmp_path: Path, name: str = "phase1") -> DORRuntime:
    return DORRuntime(f"sqlite:///{tmp_path / f'{name}.db'}")


def _context(
    runtime: DORRuntime,
    organization_id: str = "org-a",
    actor_id: str = "actor-a",
):
    organization = Organization(id=organization_id, name=organization_id)
    actor = Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id)
    runtime.create_organization(organization)
    runtime.register_actor(actor, organization_id)
    role = RoleDefinition(
        id=f"workflow-executor-{actor_id}",
        name="Workflow Executor",
        capabilities=frozenset({"workflow.transition"}),
    )
    assignment = RoleAssignment(
        actor_id=actor_id,
        organization_id=organization_id,
        role_definition_id=role.id,
        created_at=datetime.now(timezone.utc),
    )
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)
    principal = Principal(
        id=actor_id,
        type="user",
        metadata={"actor_id": actor_id},
    )
    return runtime.establish_context(principal, organization_id, actor_id)


def test_runtime_boots_from_empty_database(tmp_path: Path):
    """A fresh database must be migrated and the runtime must become READY."""
    database = tmp_path / "empty.db"
    assert not database.exists()

    runtime = DORRuntime(f"sqlite:///{database}")
    runtime.boot()

    assert runtime.ready is True
    assert database.exists()


def test_organization_isolation(tmp_path: Path):
    """An organization must not be able to read another organization's data."""
    runtime = _runtime(tmp_path, "isolation")
    runtime.boot()

    context_a = _context(runtime, "org-a", "actor-a")
    context_b = _context(runtime, "org-b", "actor-b")
    workflow_b = runtime.create_workflow(context_b, "private-b")

    with pytest.raises(NotFoundError):
        runtime.get_workflow(context_a, workflow_b.id)

    events = runtime.get_events(context_a, workflow_b.id)
    assert events == []

    assert runtime.get_workflow(context_b, workflow_b.id).id == workflow_b.id


def test_workflow_state_transitions(tmp_path: Path):
    """Valid transitions persist; invalid transitions are rejected by the domain."""
    runtime = _runtime(tmp_path, "workflow")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "phase1")

    assert workflow.current_state.name == WorkflowState.NEW

    updated = runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)
    assert updated.current_state.name == WorkflowState.ANALYSIS

    with pytest.raises(InvalidTransitionError):
        runtime.transition_workflow(context, workflow.id, WorkflowState.RELEASED)

    reloaded = runtime.get_workflow(context, workflow.id)
    assert reloaded.current_state.name == WorkflowState.ANALYSIS


def test_event_durability(tmp_path: Path):
    """Domain events must survive a complete runtime restart."""
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
        Principal(
            id="actor-a",
            type="user",
            metadata={"actor_id": "actor-a"},
        ),
        "org-a",
        "actor-a",
    )
    after_restart = restarted.get_events(restarted_context, workflow.id)

    assert [event.id for event in after_restart] == [event.id for event in before_restart]
    assert [event.sequence for event in after_restart] == [1, 2]
    assert after_restart[1].organization_id == "org-a"
    assert restarted.get_workflow(
        restarted_context, workflow.id
    ).current_state.name == WorkflowState.ANALYSIS


def test_principal_cannot_bind_to_another_actor(tmp_path: Path):
    """Identity context must reject a Principal/Actor binding mismatch."""
    runtime = _runtime(tmp_path, "identity")
    runtime.boot()
    _context(runtime, "org-a", "actor-a")

    with pytest.raises(ContextError):
        runtime.establish_context(
            Principal(
                id="actor-a",
                type="user",
                metadata={"actor_id": "actor-b"},
            ),
            "org-a",
            "actor-a",
        )
