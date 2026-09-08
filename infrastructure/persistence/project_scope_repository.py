"""SC-101B project repository with durable active-scope current state."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from domain.project import Project, ProjectIntent, ProjectStatus
from infrastructure.persistence.models import ProjectModel
from infrastructure.persistence.repositories import RepositoryError


class ProjectScopeRepository:
    """Organization-scoped project storage including SC-101B active scope."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: Project) -> None:
        self.session.add(
            ProjectModel(
                id=project.id,
                organization_id=project.organization_id,
                name=project.name,
                description=project.description,
                status=project.status.value,
                contract_version=project.contract_version,
                intent=project.intent.canonical_dict(),
                intent_fingerprint=project.intent.fingerprint,
                project_fingerprint=project.fingerprint,
                created_by=project.created_by,
                launched_by=project.launched_by,
                launch_request_fingerprint=project.launch_request_fingerprint,
                launch_command_id=project.launch_command_id,
                created_at=project.created_at,
                updated_at=project.updated_at,
                launched_at=project.launched_at,
                revision=project.revision,
            )
        )
        self.session.flush()

    def get_for_organization(
        self,
        project_id: str,
        organization_id: str,
    ) -> Optional[Project]:
        row = self.session.scalar(
            select(ProjectModel).where(
                ProjectModel.id == project_id,
                ProjectModel.organization_id == organization_id,
            )
        )
        if row is None:
            return None
        scope = self._scope_columns(project_id, organization_id)
        project = self._to_domain(row, scope)
        if row.intent_fingerprint != project.intent.fingerprint:
            raise RepositoryError("Persisted project intent fingerprint mismatch")
        if row.project_fingerprint != project.fingerprint:
            raise RepositoryError("Persisted project fingerprint mismatch")
        return project

    def get_organization_id(self, project_id: str) -> Optional[str]:
        return self.session.scalar(
            select(ProjectModel.organization_id).where(ProjectModel.id == project_id)
        )

    def update(self, project: Project, *, expected_revision: int) -> None:
        row = self.session.scalar(
            select(ProjectModel).where(
                ProjectModel.id == project.id,
                ProjectModel.organization_id == project.organization_id,
                ProjectModel.revision == expected_revision,
            )
        )
        if row is None:
            raise RepositoryError("Project not found or revision conflict")
        row.status = project.status.value
        row.launched_by = project.launched_by
        row.launched_at = project.launched_at
        row.launch_request_fingerprint = project.launch_request_fingerprint
        row.launch_command_id = project.launch_command_id
        row.updated_at = project.updated_at
        row.revision = project.revision
        self.session.flush()
        try:
            result = self.session.execute(
                text(
                    "UPDATE projects SET "
                    "active_plan_request_fingerprint=:plan, "
                    "active_scope_activated_by=:actor, "
                    "active_scope_activated_at=:activated_at, "
                    "active_scope_command_id=:command "
                    "WHERE id=:project_id AND organization_id=:organization_id "
                    "AND revision=:revision"
                ),
                {
                    "plan": project.active_plan_request_fingerprint,
                    "actor": project.active_scope_activated_by,
                    "activated_at": project.active_scope_activated_at,
                    "command": project.active_scope_command_id,
                    "project_id": project.id,
                    "organization_id": project.organization_id,
                    "revision": project.revision,
                },
            )
        except OperationalError as exc:
            if project.status is ProjectStatus.ACTIVE:
                raise RepositoryError(
                    "Project active-scope columns are unavailable"
                ) from exc
            return
        if result.rowcount != 1:
            raise RepositoryError("Project not found or revision conflict")
        self.session.flush()

    def _scope_columns(self, project_id: str, organization_id: str) -> dict[str, object | None]:
        try:
            row = self.session.execute(
                text(
                    "SELECT active_plan_request_fingerprint, "
                    "active_scope_activated_by, active_scope_activated_at, "
                    "active_scope_command_id FROM projects "
                    "WHERE id=:project_id AND organization_id=:organization_id"
                ),
                {"project_id": project_id, "organization_id": organization_id},
            ).mappings().one_or_none()
        except OperationalError:
            return {
                "active_plan_request_fingerprint": None,
                "active_scope_activated_by": None,
                "active_scope_activated_at": None,
                "active_scope_command_id": None,
            }
        if row is None:
            return {
                "active_plan_request_fingerprint": None,
                "active_scope_activated_by": None,
                "active_scope_activated_at": None,
                "active_scope_command_id": None,
            }
        return dict(row)

    @staticmethod
    def _to_domain(row: ProjectModel, scope: dict[str, object | None]) -> Project:
        intent = ProjectIntent(
            goal=row.intent["goal"],
            description=row.intent.get("description", ""),
            priority=row.intent.get("priority", "medium"),
            constraints=row.intent.get("constraints", {}),
            required_capabilities=tuple(row.intent.get("required_capabilities", [])),
        )
        return Project(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            description=row.description,
            intent=intent,
            status=ProjectStatus(row.status),
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            launched_by=row.launched_by,
            launched_at=row.launched_at,
            launch_request_fingerprint=row.launch_request_fingerprint,
            launch_command_id=row.launch_command_id,
            active_plan_request_fingerprint=scope["active_plan_request_fingerprint"],
            active_scope_activated_by=scope["active_scope_activated_by"],
            active_scope_activated_at=scope["active_scope_activated_at"],
            active_scope_command_id=scope["active_scope_command_id"],
            revision=row.revision,
            contract_version=row.contract_version,
        )


ProjectRepository = ProjectScopeRepository

__all__ = ["ProjectRepository", "ProjectScopeRepository"]
