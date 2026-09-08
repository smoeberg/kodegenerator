"""Governed PC-101 project lifecycle command boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from domain.authorization_audit import create_authorization_audit_event
from domain.event import Event, EventType
from domain.project import Project, ProjectContractError
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import CommandConflictError
from runtime.project_completion_evidence import (
    ProjectCompletionEvidence,
    ProjectCompletionEvidenceVerifier,
)
from runtime.project_runtime import ProjectCommandResult, ProjectNotFoundError
from services.authorization_service import AuthorizationService

if TYPE_CHECKING:
    from runtime.context import OrganizationContext
    from runtime.core import DORRuntime

PROJECT_COMPLETE_ACTION = "project.complete"
PROJECT_CANCEL_ACTION = "project.cancel"
PROJECT_ARCHIVE_ACTION = "project.archive"


def _text(name: str, value: str, max_length: int = 128) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProjectContractError(f"{name} must be canonical non-empty text")
    if len(value) > max_length:
        raise ProjectContractError(f"{name} exceeds {max_length} characters")


def _digest(name: str, value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ProjectContractError(f"{name} must be lowercase SHA-256")


@dataclass(frozen=True)
class RequestProjectCompletionCommand:
    command_id: str
    organization_id: str
    project_id: str
    expected_revision: int
    expected_plan_request_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("command_id", "organization_id", "project_id"):
            _text(name, getattr(self, name))
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ProjectContractError("expected_revision must be non-negative")
        _digest("expected_plan_request_fingerprint", self.expected_plan_request_fingerprint)

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CompleteProjectCommand:
    command_id: str
    organization_id: str
    project_id: str
    expected_revision: int
    expected_plan_request_fingerprint: str
    evidence: ProjectCompletionEvidence

    def __post_init__(self) -> None:
        for name in ("command_id", "organization_id", "project_id"):
            _text(name, getattr(self, name))
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ProjectContractError("expected_revision must be non-negative")
        _digest("expected_plan_request_fingerprint", self.expected_plan_request_fingerprint)
        if not isinstance(self.evidence, ProjectCompletionEvidence):
            raise ProjectContractError("evidence must be ProjectCompletionEvidence")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "expected_revision": self.expected_revision,
            "expected_plan_request_fingerprint": self.expected_plan_request_fingerprint,
            "evidence": dict(self.evidence.__dict__),
        }


@dataclass(frozen=True)
class CancelProjectCommand:
    command_id: str
    organization_id: str
    project_id: str
    expected_revision: int
    reason: str

    def __post_init__(self) -> None:
        for name in ("command_id", "organization_id", "project_id"):
            _text(name, getattr(self, name))
        _text("reason", self.reason, 2_000)
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ProjectContractError("expected_revision must be non-negative")

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ArchiveProjectCommand:
    command_id: str
    organization_id: str
    project_id: str
    expected_revision: int

    def __post_init__(self) -> None:
        for name in ("command_id", "organization_id", "project_id"):
            _text(name, getattr(self, name))
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ProjectContractError("expected_revision must be non-negative")

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


LifecycleCommand = (
    RequestProjectCompletionCommand
    | CompleteProjectCommand
    | CancelProjectCommand
    | ArchiveProjectCommand
)


class ProjectLifecycleRuntime:
    """Atomic lifecycle mutations over the existing Project aggregate authority."""

    def __init__(self, runtime: "DORRuntime") -> None:
        self.runtime = runtime

    def request_completion(self, context: "OrganizationContext", command: RequestProjectCompletionCommand) -> ProjectCommandResult:
        return self._execute(context, command, PROJECT_COMPLETE_ACTION)

    def complete_project(self, context: "OrganizationContext", command: CompleteProjectCommand) -> ProjectCommandResult:
        return self._execute(context, command, PROJECT_COMPLETE_ACTION)

    def cancel_project(self, context: "OrganizationContext", command: CancelProjectCommand) -> ProjectCommandResult:
        return self._execute(context, command, PROJECT_CANCEL_ACTION)

    def archive_project(self, context: "OrganizationContext", command: ArchiveProjectCommand) -> ProjectCommandResult:
        return self._execute(context, command, PROJECT_ARCHIVE_ACTION)

    def _execute(self, context: "OrganizationContext", command: LifecycleCommand, capability: str) -> ProjectCommandResult:
        self.runtime._require_ready()
        if command.organization_id != context.organization_id:
            raise PermissionError("command organization does not match runtime context")

        now = datetime.now(timezone.utc)
        with self.runtime.database.session(context.organization_id) as session:
            with UnitOfWork(session) as uow:
                resource_org = uow.projects.get_organization_id(command.project_id)
                decision = AuthorizationService(uow).authorize(
                    principal=context.principal,
                    actor_id=context.actor_id,
                    organization_id=context.organization_id,
                    capability_id=capability,
                    resource_id=command.project_id,
                    resource_organization_id=resource_org,
                )
                if not decision.allowed:
                    from runtime.core import CommandAuthorizationError
                    raise CommandAuthorizationError(decision)

                existing = uow.commands.get(command.command_id)
                if existing is not None:
                    if (
                        existing.organization_id != context.organization_id
                        or existing.actor_id != context.actor_id
                        or existing.command_type != type(command).__name__
                        or existing.payload != command.payload
                    ):
                        raise CommandConflictError("command_id replay changed lifecycle semantics")
                    project = uow.projects.get_for_organization(command.project_id, context.organization_id)
                    if project is None:
                        raise ProjectNotFoundError(f"Project not found: {command.project_id}")
                    return ProjectCommandResult(command.command_id, project, True)

                project = uow.projects.get_for_organization(command.project_id, context.organization_id)
                if project is None:
                    raise ProjectNotFoundError(f"Project not found: {command.project_id}")
                before_revision = project.revision
                if before_revision != command.expected_revision:
                    raise ProjectContractError("project revision conflict")

                event_type: EventType
                metadata: dict[str, Any]
                if isinstance(command, RequestProjectCompletionCommand):
                    changed = project.request_completion(
                        actor_id=context.actor_id,
                        command_id=command.command_id,
                        expected_revision=command.expected_revision,
                        expected_plan_request_fingerprint=command.expected_plan_request_fingerprint,
                        timestamp=now,
                    )
                    event_type = EventType.PROJECT_COMPLETION_REQUESTED
                    metadata = {"plan_request_fingerprint": command.expected_plan_request_fingerprint}
                elif isinstance(command, CompleteProjectCommand):
                    if project.active_plan_request_fingerprint != command.expected_plan_request_fingerprint:
                        raise ProjectContractError("active plan fingerprint changed")
                    record = ProjectCompletionEvidenceVerifier(session).verify(
                        project=project,
                        evidence=command.evidence,
                        completed_by=context.actor_id,
                        completed_at=now,
                    )
                    # Re-resolve authoritative project state after evidence lookup and
                    # before attaching proof. OCC update below is the final race fence.
                    current = uow.projects.get_for_organization(command.project_id, context.organization_id)
                    if current is None or current.revision != command.expected_revision or current.active_plan_request_fingerprint != command.expected_plan_request_fingerprint:
                        raise ProjectContractError("project changed during completion verification")
                    uow.project_completion_records.add(record)
                    changed = current.complete(record=record, expected_revision=command.expected_revision)
                    event_type = EventType.PROJECT_COMPLETED
                    metadata = {"completion_record_id": record.record_id}
                elif isinstance(command, CancelProjectCommand):
                    changed = project.cancel(
                        actor_id=context.actor_id,
                        command_id=command.command_id,
                        reason=command.reason,
                        expected_revision=command.expected_revision,
                        timestamp=now,
                    )
                    event_type = EventType.PROJECT_CANCELLED
                    metadata = {"reason": command.reason}
                else:
                    changed = project.archive(
                        actor_id=context.actor_id,
                        command_id=command.command_id,
                        expected_revision=command.expected_revision,
                        timestamp=now,
                    )
                    event_type = EventType.PROJECT_ARCHIVED
                    metadata = {"archived_from_status": changed.archived_from_status.value}

                uow.events.append(create_authorization_audit_event(
                    decision,
                    command_id=command.command_id,
                    command_type=type(command).__name__,
                    allowed=True,
                    aggregate_type="project",
                ))
                uow.events.append(Event(
                    event_type=event_type,
                    aggregate_id=changed.id,
                    aggregate_type="project",
                    organization_id=changed.organization_id,
                    actor_id=context.actor_id,
                    correlation_id=command.command_id,
                    metadata={
                        "project_id": changed.id,
                        "status": changed.status.value,
                        "project_revision": changed.revision,
                        **metadata,
                    },
                ))
                uow.projects.update(changed, expected_revision=before_revision)
                uow.commands.add(
                    command_id=command.command_id,
                    organization_id=context.organization_id,
                    actor_id=context.actor_id,
                    command_type=type(command).__name__,
                    payload=command.payload,
                    aggregate_id=changed.id,
                    created_at=now,
                )
                return ProjectCommandResult(command.command_id, changed, False)


__all__ = [
    "ArchiveProjectCommand",
    "CancelProjectCommand",
    "CompleteProjectCommand",
    "ProjectLifecycleRuntime",
    "RequestProjectCompletionCommand",
]
