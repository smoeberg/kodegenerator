"""P3-07 gates: authorization outcomes are auditable through domain events."""
from pathlib import Path
import pytest
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.event import EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import AdvanceWorkflowCommand
from runtime.core import CommandAuthorizationError, DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'authorization-audit.db'}"); runtime.boot(); return runtime


def _context(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"):
    runtime.create_organization(Organization(id=organization_id, name=organization_id)); runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}), organization_id, actor_id)


def _grant_transition(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    role = RoleDefinition(id=f"workflow.operator.{organization_id}.{actor_id}", name="Workflow Operator", organization_id=organization_id, capabilities=frozenset({"workflow.transition"}))
    assignment = RoleAssignment(actor_id=actor_id, organization_id=organization_id, role_definition_id=role.id)
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role); uow.authority.assign_role(assignment)


def _command(context, workflow_id: str, command_id: str) -> AdvanceWorkflowCommand:
    return AdvanceWorkflowCommand(command_id=command_id, organization_id=context.organization_id, workflow_id=workflow_id, target_state=WorkflowState.ANALYSIS)


def test_denied_command_persists_authorization_audit_without_mutation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime); workflow = runtime.create_workflow(context, "protected")
    with pytest.raises(CommandAuthorizationError): runtime.execute_command(context, _command(context, workflow.id, "cmd-denied"))
    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW
    events = runtime.get_events(context, workflow.id, include_authorization_audit=True); audit = [event for event in events if event.event_type is EventType.AUTHORIZATION_DENIED]
    assert len(audit) == 1; assert audit[0].actor_id == context.actor_id; assert audit[0].organization_id == context.organization_id; assert audit[0].correlation_id == "cmd-denied"
    assert audit[0].metadata["command_id"] == "cmd-denied"; assert audit[0].metadata["capability_id"] == "workflow.transition"; assert audit[0].metadata["reason_code"] == "capability_not_granted"; assert "payload" not in audit[0].metadata


def test_allowed_command_persists_grant_audit_in_same_event_stream(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime); _grant_transition(runtime, context.organization_id, context.actor_id); workflow = runtime.create_workflow(context, "protected")
    runtime.execute_command(context, _command(context, workflow.id, "cmd-allowed")); events = runtime.get_events(context, workflow.id, include_authorization_audit=True)
    assert EventType.AUTHORIZATION_GRANTED in [event.event_type for event in events]; assert EventType.WORKFLOW_STATE_CHANGED in [event.event_type for event in events]
    grant = next(event for event in events if event.event_type is EventType.AUTHORIZATION_GRANTED)
    assert grant.actor_id == context.actor_id; assert grant.organization_id == context.organization_id; assert grant.correlation_id == "cmd-allowed"; assert grant.metadata["allowed"] is True; assert grant.metadata["reason_code"] == "capability_granted"; assert grant.metadata["capability_id"] == "workflow.transition"


def test_cross_organization_denial_is_audited_only_in_requesting_org(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context_a = _context(runtime, "org-a", "actor-a"); context_b = _context(runtime, "org-b", "actor-b"); _grant_transition(runtime, "org-b", "actor-b"); workflow_a = runtime.create_workflow(context_a, "org-a-workflow")
    with pytest.raises(CommandAuthorizationError): runtime.execute_command(context_a, _command(context_a, workflow_a.id, "cmd-cross-org"))
    events_a = runtime.get_events(context_a, workflow_a.id, include_authorization_audit=True)
    assert any(event.event_type is EventType.AUTHORIZATION_DENIED for event in events_a); assert all(event.organization_id == "org-a" for event in events_a)
    assert runtime.get_events(context_b, workflow_a.id, include_authorization_audit=True) == []
