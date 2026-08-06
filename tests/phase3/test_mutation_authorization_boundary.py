"""P3-08 acceptance tests for the complete workflow mutation boundary."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.event import EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import CommandAuthorizationError, DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'p3-08.db'}")
    runtime.boot()
    return runtime


def _context(runtime: DORRuntime, *, authorized: bool):
    organization = Organization(id="org-a", name="org-a")
    actor = Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a")
    runtime.create_organization(organization)
    runtime.register_actor(actor, "org-a")

    if authorized:
        role = RoleDefinition(
            id="workflow-executor",
            name="Workflow Executor",
            capabilities=frozenset({"workflow.transition"}),
        )
        assignment = RoleAssignment(
            actor_id="actor-a",
            organization_id="org-a",
            role_definition_id=role.id,
            created_at=datetime.now(timezone.utc),
        )
        with runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.authority.add_role_definition(role)
                uow.authority.assign_role(assignment)

    return runtime.establish_context(
        Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}),
        "org-a",
        "actor-a",
    )


def test_direct_transition_is_denied_without_capability(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime, authorized=False)
    workflow = runtime.create_workflow(context, "protected")

    with pytest.raises(CommandAuthorizationError) as exc:
        runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)

    assert exc.value.decision.allowed is False
    assert exc.value.decision.reason_code == "capability_not_granted"
    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW

    events = runtime.get_events(context, workflow.id, include_authorization_audit=True)
    assert [event.event_type for event in events] == [
        EventType.WORKFLOW_CREATED,
        EventType.AUTHORIZATION_DENIED,
    ]
    assert events[-1].metadata["capability_id"] == "workflow.transition"
    assert events[-1].metadata["command_type"] == "DirectWorkflowTransition"
    assert events[-1].metadata["reason_code"] == "capability_not_granted"


def test_direct_transition_is_allowed_with_capability(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime, authorized=True)
    workflow = runtime.create_workflow(context, "protected")

    updated = runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)

    assert updated.current_state.name == WorkflowState.ANALYSIS
    events = runtime.get_events(context, workflow.id, include_authorization_audit=True)
    assert [event.event_type for event in events] == [
        EventType.WORKFLOW_CREATED,
        EventType.AUTHORIZATION_GRANTED,
        EventType.WORKFLOW_STATE_CHANGED,
    ]
    assert events[1].metadata["capability_id"] == "workflow.transition"
    assert events[1].metadata["command_type"] == "DirectWorkflowTransition"
    assert events[1].metadata["allowed"] is True


def test_direct_transition_authorization_is_organization_scoped(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime, authorized=True)

    other_context = runtime.establish_context(
        Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}),
        "org-a",
        "actor-a",
    )
    workflow = runtime.create_workflow(other_context, "same-org")

    updated = runtime.transition_workflow(
        context,
        workflow.id,
        WorkflowState.ANALYSIS,
    )
    assert updated.current_state.name == WorkflowState.ANALYSIS
