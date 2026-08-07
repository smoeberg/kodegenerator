"""Canonical runtime boundary for authority lifecycle mutations."""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from domain.authority import AuthorizationDecision, RoleAssignment, RoleDefinition
from domain.authority_audit import create_authority_mutation_audit_event
from domain.authorization_audit import create_authorization_audit_event
from infrastructure.persistence.uow import UnitOfWork
from services.authorization_service import AuthorizationService

if TYPE_CHECKING:
    from runtime.context import OrganizationContext
    from runtime.core import DORRuntime


class AuthorityRuntime:
    """Organization-scoped, authorization-protected authority mutations."""

    def __init__(self, runtime: "DORRuntime") -> None:
        self.runtime = runtime

    def _authorize(self, context: "OrganizationContext", capability_id: str, resource_id: str | None, resource_organization_id: str | None) -> AuthorizationDecision:
        with self.runtime.database.session() as session:
            uow = UnitOfWork(session)
            return AuthorizationService(uow).authorize(principal=context.principal, actor_id=context.actor_id, organization_id=context.organization_id, capability_id=capability_id, resource_id=resource_id, resource_organization_id=resource_organization_id)

    def _deny(self, decision: AuthorizationDecision, command_id: str, action: str) -> None:
        from runtime.core import CommandAuthorizationError
        event = create_authorization_audit_event(decision, command_id=command_id, command_type=action, allowed=False)
        with self.runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.events.append(event)
        raise CommandAuthorizationError(decision)

    def create_role_definition(self, context: "OrganizationContext", *, role: RoleDefinition, command_id: str | None = None) -> RoleDefinition:
        self.runtime._require_ready(); command_id = command_id or str(uuid4())
        decision = self._authorize(context, "authority.role.create", role.id, role.organization_id)
        if not decision.allowed: self._deny(decision, command_id, "role_created")
        with self.runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.authority.add_role_definition(role)
                uow.events.append(create_authority_mutation_audit_event(decision, command_id=command_id, action="role_created", role_definition_id=role.id))
        return role

    def assign_role(self, context: "OrganizationContext", *, assignment: RoleAssignment, command_id: str | None = None) -> RoleAssignment:
        self.runtime._require_ready(); command_id = command_id or str(uuid4())
        decision = self._authorize(context, "authority.role.assign", assignment.role_definition_id, assignment.organization_id)
        if not decision.allowed: self._deny(decision, command_id, "role_assigned")
        with self.runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.authority.assign_role(assignment)
                uow.events.append(create_authority_mutation_audit_event(decision, command_id=command_id, action="role_assigned", role_definition_id=assignment.role_definition_id, target_actor_id=assignment.actor_id))
        return assignment

    def deactivate_role(self, context: "OrganizationContext", role_definition_id: str, command_id: str | None = None) -> None:
        self._set_role_status(context, role_definition_id, "inactive", "authority.role.deactivate", "role_deactivated", command_id)

    def activate_role(self, context: "OrganizationContext", role_definition_id: str, command_id: str | None = None) -> None:
        self._set_role_status(context, role_definition_id, "active", "authority.role.activate", "role_activated", command_id)

    def _set_role_status(self, context: "OrganizationContext", role_definition_id: str, status: str, capability_id: str, action: str, command_id: str | None) -> None:
        self.runtime._require_ready(); command_id = command_id or str(uuid4())
        decision = self._authorize(context, capability_id, role_definition_id, context.organization_id)
        if not decision.allowed: self._deny(decision, command_id, action)
        with self.runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.authority.set_role_definition_status(role_definition_id, context.organization_id, status)
                uow.events.append(create_authority_mutation_audit_event(decision, command_id=command_id, action=action, role_definition_id=role_definition_id))

    def deactivate_assignment(self, context: "OrganizationContext", actor_id: str, role_definition_id: str, command_id: str | None = None) -> None:
        self._set_assignment_status(context, actor_id, role_definition_id, "inactive", "authority.role.deactivate", "role_assignment_deactivated", command_id)

    def activate_assignment(self, context: "OrganizationContext", actor_id: str, role_definition_id: str, command_id: str | None = None) -> None:
        self._set_assignment_status(context, actor_id, role_definition_id, "active", "authority.role.activate", "role_assignment_activated", command_id)

    def revoke_assignment(self, context: "OrganizationContext", actor_id: str, role_definition_id: str, command_id: str | None = None) -> None:
        self._set_assignment_status(context, actor_id, role_definition_id, "revoked", "authority.role.revoke", "role_revoked", command_id)

    def _set_assignment_status(self, context: "OrganizationContext", actor_id: str, role_definition_id: str, status: str, capability_id: str, action: str, command_id: str | None) -> None:
        self.runtime._require_ready(); command_id = command_id or str(uuid4())
        decision = self._authorize(context, capability_id, role_definition_id, context.organization_id)
        if not decision.allowed: self._deny(decision, command_id, action)
        with self.runtime.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.authority.set_assignment_status(actor_id, context.organization_id, role_definition_id, status)
                uow.events.append(create_authority_mutation_audit_event(decision, command_id=command_id, action=action, role_definition_id=role_definition_id, target_actor_id=actor_id))
