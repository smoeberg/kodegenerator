"""P3-09 gates for the hardened authorization boundary."""
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
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'p3-09.db'}")
    runtime.boot()
    return runtime


def _context(runtime: DORRuntime, organization_id: str, actor_id: str):
    runtime.create_organization(Organization(id=organization_id, name=organization_id))
    runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}), organization_id, actor_id)


def _grant_transition(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    role_id = f"workflow.operator.{organization_id}.{actor_id}"
    role = RoleDefinition(id=role_id, name="Workflow Operator", organization_id=organization_id, capabilities=frozenset({"workflow.transition"}))
    assignment = RoleAssignment(actor_id=actor_id, organization_id=organization_id, role_definition_id=role_id)
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)


def _command(context, workflow_id: str, command_id: str = "p3-09-command") -> AdvanceWorkflowCommand:
    return AdvanceWorkflowCommand(command_id=command_id, organization_id=context.organization_id, workflow_id=workflow_id, target_state=WorkflowState.ANALYSIS)


def test_cross_organization_resource_is_denied_and_audited(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context_a = _context(runtime, "org-a", "actor-a"); context_b = _context(runtime, "org-b", "actor-b")
    _grant_transition(runtime, "org-a", "actor-a"); _grant_transition(runtime, "org-b", "actor-b"); workflow_b = runtime.create_workflow(context_b, "private-b")
    with pytest.raises(CommandAuthorizationError) as exc: runtime.execute_command(context_a, _command(context_a, workflow_b.id, "cross-org"))
    assert exc.value.decision.reason_code == "resource_not_accessible"
    assert runtime.get_workflow(context_b, workflow_b.id).current_state.name == WorkflowState.NEW
    audit = runtime.get_events(context_a, workflow_b.id, include_authorization_audit=True)
    assert audit[-1].event_type == EventType.AUTHORIZATION_DENIED; assert audit[-1].organization_id == "org-a"


def test_command_organization_mismatch_is_denied_and_audited(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); _grant_transition(runtime, "org-a", "actor-a"); workflow = runtime.create_workflow(context, "protected")
    command = AdvanceWorkflowCommand(command_id="wrong-org", organization_id="org-b", workflow_id=workflow.id, target_state=WorkflowState.ANALYSIS)
    with pytest.raises(CommandAuthorizationError) as exc: runtime.execute_command(context, command)
    assert exc.value.decision.reason_code == "command_organization_mismatch"
    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW
    audit = runtime.get_events(context, workflow.id, include_authorization_audit=True)
    assert audit[-1].event_type == EventType.AUTHORIZATION_DENIED


def test_legacy_transition_path_cannot_bypass_authorization(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); workflow = runtime.create_workflow(context, "protected")
    with pytest.raises(CommandAuthorizationError) as exc: runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)
    assert exc.value.decision.reason_code == "capability_not_granted"
    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW


def test_legacy_transition_path_uses_canonical_authorization_when_granted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); _grant_transition(runtime, "org-a", "actor-a"); workflow = runtime.create_workflow(context, "protected")
    result = runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)
    assert result.current_state.name == WorkflowState.ANALYSIS
