"""P3-10 gates for deterministic authorization decision integrity."""
from pathlib import Path
import pytest
from domain.actor import Actor, ActorType
from domain.authorization_audit import create_authorization_audit_event
from domain.authority import AuthorizationDecision, RoleAssignment, RoleDefinition
from domain.event import EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import AdvanceWorkflowCommand
from runtime.core import DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'p3-10.db'}"); runtime.boot(); return runtime


def _context(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"):
    runtime.create_organization(Organization(id=organization_id, name=organization_id)); runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}), organization_id, actor_id)


def _grant_transition(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    role = RoleDefinition(id=f"workflow.operator.{organization_id}.{actor_id}", name="Workflow Operator", organization_id=organization_id, capabilities=frozenset({"workflow.transition"}))
    assignment = RoleAssignment(actor_id=actor_id, organization_id=organization_id, role_definition_id=role.id)
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role); uow.authority.assign_role(assignment)


def test_identical_decisions_have_identical_fingerprint() -> None:
    kwargs = dict(allowed=False, reason="Actor does not hold the requested capability", reason_code="capability_not_granted", actor_id="actor-a", principal_id="actor-a", organization_id="org-a", capability_id="workflow.transition", resource_id="workflow-a", resource_organization_id="org-a")
    assert AuthorizationDecision(**kwargs).fingerprint == AuthorizationDecision(**kwargs).fingerprint
    assert len(AuthorizationDecision(**kwargs).fingerprint) == 64


def test_decision_contract_rejects_inconsistent_outcome() -> None:
    with pytest.raises(ValueError, match="allowed flag conflicts"):
        AuthorizationDecision(allowed=True, reason="Actor does not hold the requested capability", reason_code="capability_not_granted", actor_id="actor-a", principal_id="actor-a", organization_id="org-a", capability_id="workflow.transition")


def test_audit_event_preserves_decision_integrity(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime); _grant_transition(runtime, context.organization_id, context.actor_id); workflow = runtime.create_workflow(context, "protected")
    runtime.execute_command(context, AdvanceWorkflowCommand(command_id="p3-10-integrity", organization_id=context.organization_id, workflow_id=workflow.id, target_state=WorkflowState.ANALYSIS))
    events = runtime.get_events(context, workflow.id, include_authorization_audit=True); grant = next(event for event in events if event.event_type is EventType.AUTHORIZATION_GRANTED)
    assert grant.metadata["allowed"] is True; assert grant.metadata["resource_id"] == workflow.id; assert grant.metadata["resource_organization_id"] == context.organization_id; assert len(grant.metadata["decision_fingerprint"]) == 64


def test_audit_builder_rejects_outcome_mismatch() -> None:
    decision = AuthorizationDecision(allowed=False, reason="Actor does not hold the requested capability", reason_code="capability_not_granted", actor_id="actor-a", principal_id="actor-a", organization_id="org-a", capability_id="workflow.transition", resource_id="workflow-a", resource_organization_id="org-a")
    with pytest.raises(ValueError, match="Audit outcome must match"):
        create_authorization_audit_event(decision, command_id="cmd-a", command_type="AdvanceWorkflowCommand", allowed=True)
