"""Governed SC-101B active project scope command and runtime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError, OperationalError

from domain.authorization_audit import create_authorization_audit_event
from domain.event import Event, EventType
from domain.project import Project, ProjectContractError, ProjectStateError, ProjectStatus
from infrastructure.persistence.repositories import RepositoryError
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import CommandConflictError
from services.authorization_service import AuthorizationService

if TYPE_CHECKING:
    from runtime.context import OrganizationContext
    from runtime.core import DORRuntime

PROJECT_SCOPE_ACTIVATE_ACTION = "project.scope.activate"
_COMMAND_RETRY_LIMIT = 3
_COMMAND_RETRY_DELAY_SECONDS = 0.02


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProjectContractError(f"{name} must be a canonical non-empty string")
    if len(value) > 128:
        raise ProjectContractError(f"{name} exceeds 128 characters")
    return value


def _digest(name: str, value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ProjectContractError(f"{name} must be lowercase SHA-256")
    return value


class ActiveProjectScopeError(RuntimeError):
    """The requested project/plan is not the server-owned current active scope."""


class ProjectScopeNotFoundError(RuntimeError):
    """The target project does not exist inside the authenticated tenant."""


@dataclass(frozen=True)
class ActivateProjectScopeCommand:
    command_id: str
    organization_id: str
    project_id: str
    plan_request_fingerprint: str
    expected_revision: int

    def __post_init__(self) -> None:
        _text("command_id", self.command_id)
        _text("organization_id", self.organization_id)
        _text("project_id", self.project_id)
        _digest("plan_request_fingerprint", self.plan_request_fingerprint)
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ProjectContractError("expected_revision must be a positive integer")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0",
            "command_type": type(self).__name__,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
            "expected_revision": self.expected_revision,
        }


@dataclass(frozen=True)
class ProjectScopeCommandResult:
    command_id: str
    project: Project
    replayed: bool


class ActiveProjectScopeResolver:
    """Read the materialized project row and fail closed on stale scope."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def require(
        self,
        organization_id: str,
        project_id: str,
        plan_request_fingerprint: str,
    ) -> Project:
        _text("organization_id", organization_id)
        _text("project_id", project_id)
        _digest("plan_request_fingerprint", plan_request_fingerprint)
        with self.database.session(organization_id) as session:
            project = UnitOfWork(session).projects.get_for_organization(
                project_id,
                organization_id,
            )
        if project is None:
            raise ActiveProjectScopeError("project is unavailable in the organization")
        if project.status is not ProjectStatus.ACTIVE:
            raise ActiveProjectScopeError("project has no active executable scope")
        if project.active_plan_request_fingerprint != plan_request_fingerprint:
            raise ActiveProjectScopeError("plan is not the project's current active scope")
        return project


class ProjectScopeRuntime:
    """Atomic, authorized active-scope mutation over the existing Project aggregate."""

    def __init__(self, runtime: "DORRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _assert_existing_command(
        existing: Any,
        *,
        context: "OrganizationContext",
        command: ActivateProjectScopeCommand,
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

    def activate(
        self,
        context: "OrganizationContext",
        command: ActivateProjectScopeCommand,
    ) -> ProjectScopeCommandResult:
        self.runtime._require_ready()
        if command.organization_id != context.organization_id:
            from domain.authority import AuthorizationDecision
            from runtime.core import CommandAuthorizationError

            decision = AuthorizationDecision(
                allowed=False,
                reason="Command organization does not match runtime context",
                reason_code="command_organization_mismatch",
                actor_id=context.actor_id,
                principal_id=context.principal.id,
                organization_id=context.organization_id,
                capability_id=PROJECT_SCOPE_ACTIVATE_ACTION,
                resource_id=command.project_id,
                resource_organization_id=context.organization_id,
            )
            with self.runtime.database.session(context.organization_id) as session:
                with UnitOfWork(session) as uow:
                    uow.events.append(
                        create_authorization_audit_event(
                            decision,
                            command_id=command.command_id,
                            command_type=type(command).__name__,
                            allowed=False,
                            aggregate_type="project",
                        )
                    )
            raise CommandAuthorizationError(decision)

        for attempt in range(_COMMAND_RETRY_LIMIT):
            try:
                return self._activate_once(context, command)
            except (IntegrityError, OperationalError, RepositoryError) as exc:
                retryable = isinstance(exc, (IntegrityError, RepositoryError)) or (
                    "database is locked" in str(exc).lower()
                )
                if not retryable or attempt == _COMMAND_RETRY_LIMIT - 1:
                    raise
                sleep(_COMMAND_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("unreachable project scope activation retry state")

    def _activate_once(
        self,
        context: "OrganizationContext",
        command: ActivateProjectScopeCommand,
    ) -> ProjectScopeCommandResult:
        from runtime.core import CommandAuthorizationError

        denied = None
        result = None
        with self.runtime.database.session(context.organization_id) as session:
            with UnitOfWork(session) as uow:
                resource_organization_id = uow.projects.get_organization_id(command.project_id)
                decision = AuthorizationService(uow).authorize(
                    principal=context.principal,
                    actor_id=context.actor_id,
                    organization_id=context.organization_id,
                    capability_id=PROJECT_SCOPE_ACTIVATE_ACTION,
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
                            raise ProjectScopeNotFoundError(
                                "completed scope command has no persisted project"
                            )
                        result = ProjectScopeCommandResult(
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
                            raise ProjectScopeNotFoundError(
                                f"Project not found: {command.project_id}"
                            )
                        if project.revision != command.expected_revision:
                            raise ProjectStateError("project revision conflict")
                        superseded = project.active_plan_request_fingerprint
                        activated = project.activate_scope(
                            actor_id=context.actor_id,
                            command_id=command.command_id,
                            plan_request_fingerprint=command.plan_request_fingerprint,
                            expected_revision=command.expected_revision,
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
                                event_type=EventType.PROJECT_SCOPE_ACTIVATED,
                                aggregate_id=activated.id,
                                aggregate_type="project",
                                organization_id=activated.organization_id,
                                actor_id=context.actor_id,
                                correlation_id=command.command_id,
                                metadata={
                                    "contract_version": activated.contract_version,
                                    "project_id": activated.id,
                                    "plan_request_fingerprint": activated.active_plan_request_fingerprint,
                                    "superseded_plan_request_fingerprint": superseded,
                                    "status": activated.status.value,
                                    "revision": activated.revision,
                                },
                            )
                        )
                        uow.projects.update(
                            activated,
                            expected_revision=command.expected_revision,
                        )
                        uow.commands.add(
                            command_id=command.command_id,
                            organization_id=context.organization_id,
                            actor_id=context.actor_id,
                            command_type=type(command).__name__,
                            payload=command.payload,
                            aggregate_id=activated.id,
                            created_at=datetime.now(timezone.utc),
                        )
                        result = ProjectScopeCommandResult(
                            command_id=command.command_id,
                            project=activated,
                            replayed=False,
                        )
        if denied is not None:
            with self.runtime.database.session(context.organization_id) as session:
                with UnitOfWork(session) as uow:
                    uow.events.append(
                        create_authorization_audit_event(
                            denied,
                            command_id=command.command_id,
                            command_type=type(command).__name__,
                            allowed=False,
                            aggregate_type="project",
                        )
                    )
            raise CommandAuthorizationError(denied)
        if result is None:
            raise RuntimeError("scope activation completed without a result")
        return result


__all__ = [
    "ActiveProjectScopeError",
    "ActiveProjectScopeResolver",
    "ActivateProjectScopeCommand",
    "PROJECT_SCOPE_ACTIVATE_ACTION",
    "ProjectScopeCommandResult",
    "ProjectScopeNotFoundError",
    "ProjectScopeRuntime",
]
