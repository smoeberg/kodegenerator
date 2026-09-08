"""Governed project repository with durable active-scope and lifecycle state."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.project import Project, ProjectCompletionRecord, ProjectIntent, ProjectStatus
from infrastructure.persistence.models import ProjectCompletionRecordModel, ProjectModel
from infrastructure.persistence.repositories import RepositoryError


class ProjectScopeRepository:
    """Organization-scoped project storage including SC-101B and PC-101 state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: Project) -> None:
        self.session.add(self._to_model(project))
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
        project = self._to_domain(row)
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
        row.active_plan_request_fingerprint = project.active_plan_request_fingerprint
        row.active_scope_activated_by = project.active_scope_activated_by
        row.active_scope_activated_at = project.active_scope_activated_at
        row.active_scope_command_id = project.active_scope_command_id
        row.completion_requested_by = project.completion_requested_by
        row.completion_requested_at = project.completion_requested_at
        row.completion_request_command_id = project.completion_request_command_id
        row.completion_record_id = project.completion_record_id
        row.completed_by = project.completed_by
        row.completed_at = project.completed_at
        row.cancelled_by = project.cancelled_by
        row.cancelled_at = project.cancelled_at
        row.cancel_command_id = project.cancel_command_id
        row.cancellation_reason = project.cancellation_reason
        row.archived_by = project.archived_by
        row.archived_at = project.archived_at
        row.archive_command_id = project.archive_command_id
        row.archived_from_status = (
            project.archived_from_status.value
            if project.archived_from_status is not None
            else None
        )
        row.continued_from_project_id = project.continued_from_project_id
        row.updated_at = project.updated_at
        row.revision = project.revision
        self.session.flush()

    @staticmethod
    def _to_model(project: Project) -> ProjectModel:
        return ProjectModel(
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
            active_plan_request_fingerprint=project.active_plan_request_fingerprint,
            active_scope_activated_by=project.active_scope_activated_by,
            active_scope_activated_at=project.active_scope_activated_at,
            active_scope_command_id=project.active_scope_command_id,
            completion_requested_by=project.completion_requested_by,
            completion_requested_at=project.completion_requested_at,
            completion_request_command_id=project.completion_request_command_id,
            completion_record_id=project.completion_record_id,
            completed_by=project.completed_by,
            completed_at=project.completed_at,
            cancelled_by=project.cancelled_by,
            cancelled_at=project.cancelled_at,
            cancel_command_id=project.cancel_command_id,
            cancellation_reason=project.cancellation_reason,
            archived_by=project.archived_by,
            archived_at=project.archived_at,
            archive_command_id=project.archive_command_id,
            archived_from_status=(
                project.archived_from_status.value
                if project.archived_from_status is not None
                else None
            ),
            continued_from_project_id=project.continued_from_project_id,
            created_at=project.created_at,
            updated_at=project.updated_at,
            launched_at=project.launched_at,
            revision=project.revision,
        )

    @staticmethod
    def _to_domain(row: ProjectModel) -> Project:
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
            active_plan_request_fingerprint=row.active_plan_request_fingerprint,
            active_scope_activated_by=row.active_scope_activated_by,
            active_scope_activated_at=row.active_scope_activated_at,
            active_scope_command_id=row.active_scope_command_id,
            completion_requested_by=row.completion_requested_by,
            completion_requested_at=row.completion_requested_at,
            completion_request_command_id=row.completion_request_command_id,
            completion_record_id=row.completion_record_id,
            completed_by=row.completed_by,
            completed_at=row.completed_at,
            cancelled_by=row.cancelled_by,
            cancelled_at=row.cancelled_at,
            cancel_command_id=row.cancel_command_id,
            cancellation_reason=row.cancellation_reason,
            archived_by=row.archived_by,
            archived_at=row.archived_at,
            archive_command_id=row.archive_command_id,
            archived_from_status=(
                ProjectStatus(row.archived_from_status)
                if row.archived_from_status is not None
                else None
            ),
            continued_from_project_id=row.continued_from_project_id,
            revision=row.revision,
            contract_version=row.contract_version,
        )


class ProjectCompletionRecordRepository:
    """Append-only content-addressed storage for completion proof."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: ProjectCompletionRecord) -> None:
        existing = self.session.get(ProjectCompletionRecordModel, record.record_id)
        if existing is not None:
            if self._to_domain(existing) != record:
                raise RepositoryError("completion record ID collision")
            return
        project_existing = self.get_for_project(record.project_id, record.organization_id)
        if project_existing is not None and project_existing.record_id != record.record_id:
            raise RepositoryError("project already has a different completion record")
        self.session.add(
            ProjectCompletionRecordModel(
                id=record.record_id,
                organization_id=record.organization_id,
                project_id=record.project_id,
                final_project_revision=record.final_project_revision,
                onboarding_intent_id=record.onboarding_intent_id,
                plan_request_fingerprint=record.plan_request_fingerprint,
                repository_commit_sha=record.repository_commit_sha,
                delivery_certificate_ids=list(record.delivery_certificate_ids),
                traceability_manifest_ids=list(record.traceability_manifest_ids),
                integration_evidence_ids=list(record.integration_evidence_ids),
                completed_by=record.completed_by,
                completed_at=record.completed_at,
            )
        )
        self.session.flush()

    def get(self, record_id: str, organization_id: str) -> Optional[ProjectCompletionRecord]:
        row = self.session.scalar(
            select(ProjectCompletionRecordModel).where(
                ProjectCompletionRecordModel.id == record_id,
                ProjectCompletionRecordModel.organization_id == organization_id,
            )
        )
        return self._to_domain(row) if row is not None else None

    def get_for_project(
        self,
        project_id: str,
        organization_id: str,
    ) -> Optional[ProjectCompletionRecord]:
        row = self.session.scalar(
            select(ProjectCompletionRecordModel).where(
                ProjectCompletionRecordModel.project_id == project_id,
                ProjectCompletionRecordModel.organization_id == organization_id,
            )
        )
        return self._to_domain(row) if row is not None else None

    @staticmethod
    def _to_domain(row: ProjectCompletionRecordModel) -> ProjectCompletionRecord:
        record = ProjectCompletionRecord(
            organization_id=row.organization_id,
            project_id=row.project_id,
            final_project_revision=row.final_project_revision,
            onboarding_intent_id=row.onboarding_intent_id,
            plan_request_fingerprint=row.plan_request_fingerprint,
            repository_commit_sha=row.repository_commit_sha,
            delivery_certificate_ids=tuple(row.delivery_certificate_ids),
            traceability_manifest_ids=tuple(row.traceability_manifest_ids),
            integration_evidence_ids=tuple(row.integration_evidence_ids),
            completed_by=row.completed_by,
            completed_at=row.completed_at,
        )
        if record.record_id != row.id:
            raise RepositoryError("Persisted completion record fingerprint mismatch")
        return record


ProjectRepository = ProjectScopeRepository

__all__ = [
    "ProjectCompletionRecordRepository",
    "ProjectRepository",
    "ProjectScopeRepository",
]
