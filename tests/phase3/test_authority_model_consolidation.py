"""P3-12 authority model consolidation gates."""
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

ADMIN_CAPABILITIES = frozenset(
    {
        "authority.role.create",
        "authority.role.assign",
        "authority.role.activate",
        "authority.role.deactivate",
        "authority.role.revoke",
    }
)


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'p3-12.db'}")
    runtime.boot()
    return runtime


def _context(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"):
    runtime.create_organization(Organization(id=organization_id, name=organization_id))
    runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}), organization_id, actor_id)


def _seed_admin(runtime: DORRuntime, organization_id: str, actor_id: str) -> str:
    role_id = f"authority.admin.{organization_id}.{actor_id}"
    role = RoleDefinition(id=role_id, name="Authority Administrator", organization_id=organization_id, capabilities=ADMIN_CAPABILITIES)
    assignment = RoleAssignment(actor_id=actor_id, organization_id=organization_id, role_definition_id=role_id)
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)
    return role_id


def test_role_definition_is_organization_scoped(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context_a = _context(runtime, "org-a", "actor-a")
    context_b = _context(runtime, "org-b", "actor-b")
    _seed_admin(runtime, "org-a", "actor-a")
    _seed_admin(runtime, "org-b", "actor-b")
    role = RoleDefinition(id="role-a", name="Role A", organization_id="org-a", capabilities=frozenset({"workflow.transition"}))
    runtime.authority.create_role_definition(context_a, role=role)
    with pytest.raises(CommandAuthorizationError) as exc:
        runtime.authority.assign_role(context_b, assignment=RoleAssignment(actor_id="actor-b", organization_id="org-b", role_definition_id="role-a"))
    assert exc.value.decision.reason_code == "resource_not_accessible"


def test_inactive_role_denies_capability_immediately(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime)
    _seed_admin(runtime, "org-a", "actor-a")
    role = RoleDefinition(id="workflow.operator", name="Workflow Operator", organization_id="org-a", capabilities=frozenset({"workflow.transition"}))
    runtime.authority.create_role_definition(context, role=role)
    runtime.authority.assign_role(context, assignment=RoleAssignment(actor_id="actor-a", organization_id="org-a", role_definition_id=role.id))
    workflow = runtime.create_workflow(context, "protected")
    runtime.authority.deactivate_role(context, role.id)
    with pytest.raises(CommandAuthorizationError) as exc:
        runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)
    assert exc.value.decision.reason_code == "capability_not_granted"


def test_revoked_assignment_cannot_be_reactivated(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime)
    _seed_admin(runtime, "org-a", "actor-a")
    role = RoleDefinition(id="revocable", name="Revocable", organization_id="org-a", capabilities=frozenset({"workflow.transition"}))
    runtime.authority.create_role_definition(context, role=role)
    runtime.authority.assign_role(context, assignment=RoleAssignment(actor_id="actor-a", organization_id="org-a", role_definition_id=role.id))
    runtime.authority.revoke_assignment(context, "actor-a", role.id)
    with pytest.raises(ValueError, match="cannot be reactivated"):
        runtime.authority.activate_assignment(context, "actor-a", role.id)


def test_authority_mutations_are_audited_with_decision_fingerprint(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime)
    _seed_admin(runtime, "org-a", "actor-a")
    role = RoleDefinition(id="audited-role", name="Audited Role", organization_id="org-a", capabilities=frozenset({"workflow.transition"}))
    runtime.authority.create_role_definition(context, role=role, command_id="create-role")
    runtime.authority.assign_role(context, assignment=RoleAssignment(actor_id="actor-a", organization_id="org-a", role_definition_id=role.id), command_id="assign-role")
    events = runtime.get_events(context, role.id, include_authorization_audit=True)
    assert [event.event_type for event in events] == [EventType.AUTHORITY_ROLE_CREATED, EventType.AUTHORITY_ROLE_ASSIGNED]
    assert all(event.metadata["decision_fingerprint"] for event in events)
    assert all("token" not in event.metadata and "secret" not in event.metadata for event in events)


def test_legacy_actor_authority_cannot_grant_access(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime)
    context.actor.add_capability(type("Capability", (), {"id": "workflow.transition"})())
    workflow = runtime.create_workflow(context, "legacy")
    assert context.actor.can_perform("workflow.transition") is False
    with pytest.raises(CommandAuthorizationError):
        runtime.transition_workflow(context, workflow.id, WorkflowState.ANALYSIS)


def test_revocation_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "restart.db"
    runtime = DORRuntime(f"sqlite:///{database}")
    runtime.boot()
    context = _context(runtime)
    _seed_admin(runtime, "org-a", "actor-a")
    role = RoleDefinition(id="restart-role", name="Restart Role", organization_id="org-a", capabilities=frozenset({"workflow.transition"}))
    runtime.authority.create_role_definition(context, role=role)
    runtime.authority.assign_role(context, assignment=RoleAssignment(actor_id="actor-a", organization_id="org-a", role_definition_id=role.id))
    runtime.authority.revoke_assignment(context, "actor-a", role.id)
    restarted = DORRuntime(f"sqlite:///{database}")
    restarted.boot()
    restarted_context = restarted.establish_context(Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}), "org-a", "actor-a")
    workflow = restarted.create_workflow(restarted_context, "restart-protected")
    with pytest.raises(CommandAuthorizationError):
        restarted.transition_workflow(restarted_context, workflow.id, WorkflowState.ANALYSIS)
