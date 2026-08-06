"""P3-06 gates: command execution must be centrally authorized."""
from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import AdvanceWorkflowCommand
from runtime.core import CommandAuthorizationError, DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'command-auth.db'}")
    runtime.boot()
    return runtime


def _seed_context(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"):
    runtime.create_organization(Organization(id=organization_id, name=organization_id))
    runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(
        Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}),
        organization_id,
        actor_id,
    )


def _grant_transition(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    role = RoleDefinition(
        id="workflow.operator",
        name="Workflow Operator",
        capabilities=frozenset({"workflow.transition"}),
    )
    assignment = RoleAssignment(
        actor_id=actor_id,
        organization_id=organization_id,
        role_definition_id=role.id,
    )
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)


def _command(context, workflow_id: str, command_id: str = "cmd-1") -> AdvanceWorkflowCommand:
    return AdvanceWorkflowCommand(
        command_id=command_id,
        organization_id=context.organization_id,
        workflow_id=workflow_id,
        target_state=WorkflowState.ANALYSIS,
    )


def test_command_is_denied_without_transition_capability(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _seed_context(runtime)
    workflow = runtime.create_workflow(context, "protected")

    with pytest.raises(CommandAuthorizationError) as exc:
        runtime.execute_command(context, _command(context, workflow.id))

    assert exc.value.decision.allowed is False
    assert exc.value.decision.reason_code == "capability_not_granted"
    assert runtime.get_workflow(context, workflow.id).current_state == WorkflowState.NEW


def test_command_is_allowed_when_transition_capability_is_granted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _seed_context(runtime)
    _grant_transition(runtime, context.organization_id, context.actor_id)
    workflow = runtime.create_workflow(context, "protected")

    result = runtime.execute_command(context, _command(context, workflow.id))

    assert result.command_id == "cmd-1"
    assert runtime.get_workflow(context, workflow.id).current_state == WorkflowState.ANALYSIS


def test_command_is_denied_for_actor_without_capability_in_other_organization(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context_a = _seed_context(runtime, "org-a", "actor-a")
    context_b = _seed_context(runtime, "org-b", "actor-b")
    _grant_transition(runtime, "org-b", "actor-b")
    workflow_a = runtime.create_workflow(context_a, "org-a-workflow")

    with pytest.raises(CommandAuthorizationError) as exc:
        runtime.execute_command(context_a, _command(context_a, workflow_a.id, "cmd-cross-org"))

    assert exc.value.decision.reason_code == "capability_not_granted"
