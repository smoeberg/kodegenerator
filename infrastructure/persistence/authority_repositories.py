"""Persistence boundary for Phase 3 role authority."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.authority import RoleAssignment, RoleDefinition
from domain.authority_resolution import resolve_effective_capabilities

from .models import ActorModel, RoleAssignmentModel, RoleDefinitionModel


class AuthorityRepository:
    """Organization-scoped repository for role definitions and assignments."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_role_definition(self, role: RoleDefinition) -> None:
        self.session.add(
            RoleDefinitionModel(
                id=role.id,
                organization_id=role.organization_id,
                name=role.name,
                description=role.description,
                capabilities=sorted(role.capabilities),
                status=role.status,
            )
        )

    def get_role_definition(
        self, role_definition_id: str, organization_id: str
    ) -> RoleDefinition | None:
        row = self.session.scalar(
            select(RoleDefinitionModel).where(
                RoleDefinitionModel.id == role_definition_id,
                RoleDefinitionModel.organization_id == organization_id,
            )
        )
        if row is None:
            return None
        return RoleDefinition(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            description=row.description,
            capabilities=frozenset(row.capabilities),
            status=row.status,
        )

    def assign_role(self, assignment: RoleAssignment) -> None:
        role = self.get_role_definition(
            assignment.role_definition_id, assignment.organization_id
        )
        if role is None:
            raise ValueError(
                "Role definition does not belong to organization: "
                f"{assignment.role_definition_id}@{assignment.organization_id}"
            )
        if role.status != "active":
            raise ValueError("Cannot assign an inactive role definition")

        actor_exists = self.session.scalar(
            select(ActorModel.id).where(
                ActorModel.id == assignment.actor_id,
                ActorModel.organization_id == assignment.organization_id,
            )
        )
        if actor_exists is None:
            raise ValueError(
                "Actor does not belong to organization: "
                f"{assignment.actor_id}@{assignment.organization_id}"
            )

        self.session.add(
            RoleAssignmentModel(
                actor_id=assignment.actor_id,
                organization_id=assignment.organization_id,
                role_definition_id=assignment.role_definition_id,
                status=assignment.status,
                created_at=assignment.created_at,
            )
        )

    def get_assignments(
        self, actor_id: str, organization_id: str
    ) -> list[RoleAssignment]:
        rows = self.session.scalars(
            select(RoleAssignmentModel)
            .where(
                RoleAssignmentModel.actor_id == actor_id,
                RoleAssignmentModel.organization_id == organization_id,
            )
            .order_by(RoleAssignmentModel.role_definition_id)
        ).all()
        return [
            RoleAssignment(
                actor_id=row.actor_id,
                organization_id=row.organization_id,
                role_definition_id=row.role_definition_id,
                status=row.status,
                created_at=(
                    row.created_at.replace(tzinfo=timezone.utc)
                    if row.created_at and row.created_at.tzinfo is None
                    else row.created_at
                ),
            )
            for row in rows
        ]

    def get_assignment(
        self, actor_id: str, organization_id: str, role_definition_id: str
    ) -> RoleAssignment | None:
        row = self.session.scalar(
            select(RoleAssignmentModel).where(
                RoleAssignmentModel.actor_id == actor_id,
                RoleAssignmentModel.organization_id == organization_id,
                RoleAssignmentModel.role_definition_id == role_definition_id,
            )
        )
        if row is None:
            return None
        return RoleAssignment(
            actor_id=row.actor_id,
            organization_id=row.organization_id,
            role_definition_id=row.role_definition_id,
            status=row.status,
            created_at=(
                row.created_at.replace(tzinfo=timezone.utc)
                if row.created_at and row.created_at.tzinfo is None
                else row.created_at
            ),
        )

    def set_role_definition_status(
        self, role_definition_id: str, organization_id: str, status: str
    ) -> None:
        if status not in {"active", "inactive"}:
            raise ValueError("RoleDefinition status must be active or inactive")
        row = self.session.scalar(
            select(RoleDefinitionModel).where(
                RoleDefinitionModel.id == role_definition_id,
                RoleDefinitionModel.organization_id == organization_id,
            )
        )
        if row is None:
            raise ValueError("Role definition not found")
        row.status = status
        self.session.flush()

    def set_assignment_status(
        self,
        actor_id: str,
        organization_id: str,
        role_definition_id: str,
        status: str,
    ) -> None:
        if status not in {"active", "inactive", "revoked"}:
            raise ValueError("Invalid RoleAssignment status")
        row = self.session.scalar(
            select(RoleAssignmentModel).where(
                RoleAssignmentModel.actor_id == actor_id,
                RoleAssignmentModel.organization_id == organization_id,
                RoleAssignmentModel.role_definition_id == role_definition_id,
            )
        )
        if row is None:
            raise ValueError("Role assignment not found")
        if row.status == "revoked" and status != "revoked":
            raise ValueError("Revoked role assignments cannot be reactivated")
        row.status = status
        self.session.flush()

    def revoke_assignment(
        self, actor_id: str, organization_id: str, role_definition_id: str
    ) -> None:
        self.set_assignment_status(
            actor_id, organization_id, role_definition_id, "revoked"
        )

    def get_effective_capabilities(
        self, actor_id: str, organization_id: str
    ) -> frozenset[str]:
        """Resolve effective capabilities through the canonical authority chain."""
        assignments = self.get_assignments(actor_id, organization_id)
        role_ids = {assignment.role_definition_id for assignment in assignments}
        roles = {
            role_id: role
            for role_id in role_ids
            if (role := self.get_role_definition(role_id, organization_id)) is not None
        }
        return resolve_effective_capabilities(
            actor_id,
            organization_id,
            assignments,
            roles,
        )
