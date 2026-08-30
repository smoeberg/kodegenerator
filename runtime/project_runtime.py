"""Versioned governed project command/query runtime for the Control Plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.exc import IntegrityError, OperationalError

from domain.authority import AuthorizationDecision
from domain.authorization_audit import create_authorization_audit_event
from domain.event import Event, EventType
from domain.project import Project, ProjectContractError, ProjectIntent
from infrastructure.persistence.repositories import RepositoryError
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import CommandConflictError
from services.authorization_service import AuthorizationService

if TYPE_CHECKING:
    from runtime.context import OrganizationContext
    from runtime.core import DORRuntime


PROJECT_CREATE_ACTION = "project.create"
PROJECT_LAUNCH_ACTION = "project.launch"
PROJECT_READ_ACTION = "project.read"
_COMMAND_RETRY_LIMIT = 3
_COMMAND_RETRY_DELAY_SECONDS = 0.02


def _command_text(name: str, value: str, *, max_length: int = 128) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProjectContractError(f"{name} must be a non-empty trimmed string")
    if len(value) > max_length:
        raise ProjectContractError(f"{name} exceeds {max_length} characters")


class ProjectNotFoundError(RuntimeError):
    """Raised when an organization-scoped project cannot be found."""


@dataclass(frozen=True)
class CreateProjectCommand:
    command_id: str
    organization_id: str
    name: str
    description: str
    intent: ProjectIntent

    def __post_init__(self) -> None:
        _command_text("command_id", self.command_id)
        _command_text("organization_id", self.organization_id)
        _command_text("name", self.name, max_length=255)
        if not isinstance(self.description, str) or len(self.description) > 20_000:
            raise ProjectContractError("description exceeds 20000 characters")
        if not isinstance(self.intent, ProjectIntent):
            raise ProjectContractError("intent must be a ProjectIntent")

    @property
    def project_id(self) -> str:
        return str(
            uuid5(
                NAMESPACE_URL,
                f"dor:{self.organization_id}:project:{self.command_id}",
            )
        )

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0",
            "command_type": type(self).__name__,
            "organization_id": self.organization_id,
            "name": self.name,
            "description": self.description,
            "intent": self.intent.canonical_dict(),
            "intent_fingerprint": self.intent.fingerprint,
        }


@dataclass(frozen=True)
class LaunchProjectCommand:
    command_id: str
    organization_id: str
    project_id: str
    expected_project_fingerprint: str

    def __post_init__(self) -> None:
        _command_text("command_id", self.command_id)
        _command_text("organization_id", self.organization_id)
        _command_text("project_id", self.project_id)
        fingerprint = self.expected_project_fingerprint
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ProjectContractError(
                "expected_project_fingerprint must be lowercase SHA-256"
            )

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0",
            "command_type": type(self).__name__,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "expected_project_fingerprint": self.expected_project_fingerprint,
        }


@dataclass(frozen=True)
class ProjectCommandResult:
    command_id: str
    project: Project
    replayed: bool


class ProjectRuntime:
    """Canonical project boundary used by the first-party Control Plane API."""

    def __init__(self, runtime: "DORRuntime") -> None:
        self.runtime = runtime

    def _record_denial(
        self,
        decision: AuthorizationDecision,
        *,
        command_id: str,
        command_type: str,
    ) -> None:
        from runtime.core import CommandAuthorizationError

        event = create_authorization_audit_event(
            decision,
            command_id=command_id,
            command_type=command_type,
            allowed=False,
            aggregate_type="project",
        )
        with self.runtime.database.session(decision.organization_id) as session:
            with UnitOfWork(session) as uow:
                uow.events.append(event)
        raise CommandAuthorizationError(decision)

    @staticmethod
    def _assert_existing_command(
        existing: Any,
        *,
        context: "OrganizationContext",
        command: CreateProjectCommand | LaunchProjectCommand,
    ) -> None:
        if (
            existing.organization_id != context.organization_id
            or existing.actor_id != context.actor_id
            or existing.command_type != type(command).__name__
            or existing.payload != command.payload
        ):
            raise CommandConflictError(
                f"Command ID already used with different command data: {command.command_id}"
            )

    def _organization_mismatch(
        self,
        context: "OrganizationContext",
        command: CreateProjectCommand | LaunchProjectCommand,
        *,
        capability_id: str,
        resource_id: str,
    ) -> None:
        decision = AuthorizationDecision(
            allowed=False,
            reason="Command organization does not match runtime context",
            reason_code="command_organization_mismatch",
            actor_id=context.actor_id,
            principal_id=context.principal.id,
            organization_id=context.organization_id,
            capability_id=capability_id,
            resource_id=resource_id,
            resource_organization_id=context.organization_id,
        )
        self._record_denial(
            decision,
            command_id=command.command_id,
            command_type=type(command).__name__,
        )

    def create_project(
        self,
        context: "OrganizationContext",
        command: CreateProjectCommand,
    ) -> ProjectCommandResult:
        for attempt in range(_COMMAND_RETRY_LIMIT):
            try:
                return self._create_project_once(context, command)
            except IntegrityError:
                if attempt == _COMMAND_RETRY_LIMIT - 1:
                    raise
            except OperationalError as exc:
                if (
                    "database is locked" not in str(exc).lower()
                    or attempt == _COMMAND_RETRY_LIMIT - 1
                ):
                    raise
            sleep(_COMMAND_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("unreachable project creation retry state")

    def _create_project_once(
        self,
        context: "OrganizationContext",
        command: CreateProjectCommand,
    ) -> ProjectCommandResult:
        """Authorize, persist and audit one immutable project intent atomically."""
        self.runtime._require_ready()
        if command.organization_id != context.organization_id:
            self._organization_mismatch(
                context,
                command,
                capability_id=PROJECT_CREATE_ACTION,
                resource_id=command.project_id,
            )

        denied: AuthorizationDecision | None = None
        result: ProjectCommandResult | None = None
        with self.runtime.database.session(context.organization_id) as session:
            with UnitOfWork(session) as uow:
                decision = AuthorizationService(uow).authorize(
                    principal=context.principal,
                    actor_id=context.actor_id,
                    organization_id=context.organization_id,
                    capability_id=PROJECT_CREATE_ACTION,
                    resource_id=command.project_id,
                    resource_organization_id=context.organization_id,
                )
                if not decision.allowed:
                    denied = decision
                else:
                    existing = uow.commands.get(command.command_id)
                    if existing is not None:
                        self._assert_existing_command(
                            existing,
                            context=context,
                            command=command,
                        )
                        project = uow.projects.get_for_organization(
                            existing.aggregate_id or "",
                            context.organization_id,
                        )
                        if project is None:
                            raise ProjectNotFoundError(
                                "completed create command has no persisted project"
                            )
                        result = ProjectCommandResult(
                            command_id=command.command_id,
                            project=project,
                            replayed=True,
                        )
                    else:
                        project = Project.create(
                            project_id=command.project_id,
                            organization_id=context.organization_id,
                            name=command.name,
                            description=command.description,
                            intent=command.intent,
                            actor_id=context.actor_id,
                        )
                        uow.projects.add(project)
                        uow.events.append(
                            create_authorization_audit_event(
                                decision,
                                command_id=command.command_id,
                                command_type=type(command).__name__,
                                allowed=True,
                                aggregate_type="project",
                            )
                        )
                        uow.events.append(
                            Event(
                                event_type=EventType.PROJECT_CREATED,
                                aggregate_id=project.id,
                                aggregate_type="project",
                                organization_id=project.organization_id,
                                actor_id=context.actor_id,
                                correlation_id=command.command_id,
                                metadata={
                                    "contract_version": project.contract_version,
                                    "project_id": project.id,
                                    "project_fingerprint": project.fingerprint,
                                    "intent_fingerprint": project.intent.fingerprint,
                                    "status": project.status.value,
                                },
                            )
                        )
                        uow.commands.add(
                            command_id=command.command_id,
                            organization_id=context.organization_id,
                            actor_id=context.actor_id,
                            command_type=type(command).__name__,
                            payload=command.payload,
                            aggregate_id=project.id,
                            created_at=datetime.now(timezone.utc),
                        )
                        result = ProjectCommandResult(
                            command_id=command.command_id,
                            project=project,
                            replayed=False,
                        )
        if denied is not None:
            self._record_denial(
                denied,
                command_id=command.command_id,
                command_type=type(command).__name__,
            )
        if result is None:
            raise RuntimeError("project creation completed without a result")
        return result

    def launch_project(
        self,
        context: "OrganizationContext",
        command: LaunchProjectCommand,
    ) -> ProjectCommandResult:
        for attempt in range(_COMMAND_RETRY_LIMIT):
            try:
                return self._launch_project_once(context, command)
            except IntegrityError:
                if attempt == _COMMAND_RETRY_LIMIT - 1:
                    raise
            except OperationalError as exc:
                if (
                    "database is locked" not in str(exc).lower()
                    or attempt == _COMMAND_RETRY_LIMIT - 1
                ):
                    raise
            except RepositoryError as exc:
                if (
                    "revision conflict" not in str(exc).lower()
                    or attempt == _COMMAND_RETRY_LIMIT - 1
                ):
                    raise
            sleep(_COMMAND_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("unreachable project launch retry state")

    def _launch_project_once(
        self,
        context: "OrganizationContext",
        command: LaunchProjectCommand,
    ) -> ProjectCommandResult:
        """Record a governed launch request; execution remains a later boundary."""
        self.runtime._require_ready()
        if command.organization_id != context.organization_id:
            self._organization_mismatch(
                context,
                command,
                capability_id=PROJECT_LAUNCH_ACTION,
                resource_id=command.project_id,
            )

        denied: AuthorizationDecision | None = None
        result: ProjectCommandResult | None = None
        with self.runtime.database.session(context.organization_id) as session:
            with UnitOfWork(session) as uow:
                resource_organization_id = uow.projects.get_organization_id(
                    command.project_id
                )
                decision = AuthorizationService(uow).authorize(
                    principal=context.principal,
                    actor_id=context.actor_id,
                    organization_id=context.organization_id,
                    capability_id=PROJECT_LAUNCH_ACTION,
                    resource_id=command.project_id,
                    resource_organization_id=resource_organization_id,
                )
                if not decision.allowed:
                    denied = decision
                else:
                    existing = uow.commands.get(command.command_id)
                    if existing is not None:
                        self._assert_existing_command(
                            existing,
                            context=context,
                            command=command,
                        )
                        project = uow.projects.get_for_organization(
                            existing.aggregate_id or "",
                            context.organization_id,
                        )
                        if project is None:
                            raise ProjectNotFoundError(
                                "completed launch command has no persisted project"
                            )
                        result = ProjectCommandResult(
                            command_id=command.command_id,
                            project=project,
                            replayed=True,
                        )
                    else:
                        project = uow.projects.get_for_organization(
                            command.project_id,
                            context.organization_id,
                        )
                        if project is None:
                            raise ProjectNotFoundError(
                                f"Project not found: {command.project_id}"
                            )
                        expected_revision = project.revision
                        launched = project.request_launch(
                            actor_id=context.actor_id,
                            command_id=command.command_id,
                            expected_project_fingerprint=(
                                command.expected_project_fingerprint
                            ),
                        )
                        uow.events.append(
                            create_authorization_audit_event(
                                decision,
                                command_id=command.command_id,
                                command_type=type(command).__name__,
                                allowed=True,
                                aggregate_type="project",
                            )
                        )
                        uow.events.append(
                            Event(
                                event_type=EventType.PROJECT_LAUNCH_REQUESTED,
                                aggregate_id=launched.id,
                                aggregate_type="project",
                                organization_id=launched.organization_id,
                                actor_id=context.actor_id,
                                correlation_id=command.command_id,
                                metadata={
                                    "contract_version": launched.contract_version,
                                    "project_id": launched.id,
                                    "project_fingerprint": launched.fingerprint,
                                    "launch_request_fingerprint": (
                                        launched.launch_request_fingerprint
                                    ),
                                    "status": launched.status.value,
                                    "execution_started": False,
                                },
                            )
                        )
                        uow.projects.update(
                            launched,
                            expected_revision=expected_revision,
                        )
                        uow.commands.add(
                            command_id=command.command_id,
                            organization_id=context.organization_id,
                            actor_id=context.actor_id,
                            command_type=type(command).__name__,
                            payload=command.payload,
                            aggregate_id=launched.id,
                            created_at=datetime.now(timezone.utc),
                        )
                        result = ProjectCommandResult(
                            command_id=command.command_id,
                            project=launched,
                            replayed=False,
                        )
        if denied is not None:
            self._record_denial(
                denied,
                command_id=command.command_id,
                command_type=type(command).__name__,
            )
        if result is None:
            raise RuntimeError("project launch completed without a result")
        return result

    def _authorize_read(
        self,
        context: "OrganizationContext",
        project_id: str,
    ) -> None:
        from runtime.core import CommandAuthorizationError

        with self.runtime.database.session(context.organization_id) as session:
            uow = UnitOfWork(session)
            resource_organization_id = uow.projects.get_organization_id(project_id)
            decision = AuthorizationService(uow).authorize(
                principal=context.principal,
                actor_id=context.actor_id,
                organization_id=context.organization_id,
                capability_id=PROJECT_READ_ACTION,
                resource_id=project_id,
                resource_organization_id=resource_organization_id,
            )
        if not decision.allowed:
            raise CommandAuthorizationError(decision)

    def get_project(
        self,
        context: "OrganizationContext",
        project_id: str,
    ) -> Project:
        self.runtime._require_ready()
        self._authorize_read(context, project_id)
        with self.runtime.database.session(context.organization_id) as session:
            project = UnitOfWork(session).projects.get_for_organization(
                project_id,
                context.organization_id,
            )
        if project is None:
            raise ProjectNotFoundError(f"Project not found: {project_id}")
        return project

    def get_events(
        self,
        context: "OrganizationContext",
        project_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        include_authorization_audit: bool = True,
    ) -> list[Event]:
        if after_sequence < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid project event cursor or limit")
        self.get_project(context, project_id)
        with self.runtime.database.session(context.organization_id) as session:
            events = UnitOfWork(session).events.for_aggregate(
                project_id,
                context.organization_id,
            )
        if not include_authorization_audit:
            events = [
                event
                for event in events
                if event.event_type
                not in {
                    EventType.AUTHORIZATION_GRANTED,
                    EventType.AUTHORIZATION_DENIED,
                }
            ]
        return [event for event in events if event.sequence > after_sequence][:limit]
