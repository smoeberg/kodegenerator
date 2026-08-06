"""Persistence boundary for Phase 3 role authority."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.authority import RoleAssignment, RoleDefinition

from .models import RoleAssignmentModel, RoleDefinitionModel


class AuthorityRepository:
    """Organization-scoped repository for role definitions and assignments."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_role_definition(self, role: RoleDefinition) -> None:
        self.session.add(
            RoleDefinitionModel(
                id=role.id,
                name=role.name,
                description=role.description,
                capabilities=sorted(role.capabilities),
                status=role.status,
            )
        )

    def get_role_definition(self, role_definition_id: str) -> RoleDefinition | None:
        row = self.session.get(RoleDefinitionModel, role_definition_id)
        if row is None:
            return None
        return RoleDefinition(
            id=row.id,
            name=row.name,
            description=row.description,
            capabilities=frozenset(row.capabilities),
            status=row.status,
        )

    def assign_role(self, assignment: RoleAssignment) -> None:
        role = self.get_role_definition(assignment.role_definition_id)
        if role is None:
            raise ValueError(f"Role definition not found: {assignment.role_definition_id}")
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
                created_at=row.created_at,
            )
            for row in rows
        ]
