"""DOR runtime: boot, identity context, workflows, events and commands."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import sleep
from typing import Optional
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from domain.actor import Actor
from domain.authorization_audit import create_authorization_audit_event
from domain.authority import AuthorizationDecision
from domain.event import Event, EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import InvalidTransitionError, Transition, Workflow, WorkflowState
from infrastructure.persistence.database import Database
from infrastructure.persistence.repositories import RepositoryError
from infrastructure.persistence.uow import UnitOfWork
from services.authorization_service import AuthorizationService
from .authority import AuthorityRuntime
from .commands import AdvanceWorkflowCommand, CommandConflictError, CommandResult
from .context import ContextError, OrganizationContext, establish_context


class RuntimeNotReadyError(RuntimeError):
    """Raised when runtime work is attempted before boot."""


class NotFoundError(RuntimeError):
    """Raised when an organization-scoped resource does not exist."""


class CommandAuthorizationError(PermissionError):
    """Raised when a command fails the central authorization boundary."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(f"Command denied: {decision.reason_code}: {decision.reason}")


_ALEMBIC_BOOT_LOCK = RLock()
_COMMAND_RETRY_LIMIT = 3
_COMMAND_RETRY_DELAY_SECONDS = 0.02


class DORRuntime:
    """Persistent DOR runtime with organization-scoped command execution."""

    def __init__(self, database_url: str = "sqlite:///./dor_runtime.db") -> None:
        self.database_url = database_url
        self.database = Database(database_url)
        self.ready = False
        self.authority = AuthorityRuntime(self)

    def boot(self) -> None:
        """Run the canonical database migration and mark the runtime ready."""
        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        alembic_dir = alembic_ini.parent / "alembic"
        if not alembic_ini.exists() or not alembic_dir.exists():
            raise RuntimeNotReadyError("DOR migration configuration is incomplete")
        config = Config(str(alembic_ini))
        config.set_main_option("script_location", str(alembic_dir))
        config.set_main_option("sqlalchemy.url", self.database_url)
        with _ALEMBIC_BOOT_LOCK:
            command.upgrade(config, "head")
        self.ready = True

    def _require_ready(self) -> None:
        if not self.ready:
            raise RuntimeNotReadyError("DOR runtime has not been booted")

    def create_organization(self, organization: Organization) -> None:
        self._require_ready()
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                if uow.organizations.get(organization.id) is not None:
                    raise RepositoryError(f"Organization already exists: {organization.id}")
                uow.organizations.add(organization)

    def register_actor(self, actor: Actor, organization_id: str) -> None:
        self._require_ready()
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                organization = uow.organizations.get(organization_id)
                if organization is None:
                    raise NotFoundError(f"Organization not found: {organization_id}")
                if uow.actors.get_for_organization(actor.id, organization_id) is not None:
                    raise RepositoryError(f"Actor already exists: {actor.id}")
                uow.actors.add(actor, organization_id)

    def establish_context(self, principal: Principal, organization_id: str, actor_id: str) -> OrganizationContext:
        self._require_ready()
        with self.database.session() as session:
            uow = UnitOfWork(session)
            organization = uow.organizations.get(organization_id)
            if organization is None:
                raise NotFoundError(f"Organization not found: {organization_id}")
            actor = uow.actors.get_for_organization(actor_id, organization_id)
            if actor is None:
                raise ContextError("Actor is not a member of the organization")
            actor.organization = organization
            return establish_context(principal, actor, organization)

    def create_workflow(self, context: OrganizationContext, name: str, description: str = "") -> Workflow:
        self._require_ready()
        workflow = self._new_workflow(name=name, description=description, organization=context.organization)
        event = Event(event_type=EventType.WORKFLOW_CREATED, aggregate_id=workflow.id, aggregate_type="workflow", organization_id=context.organization_id, actor_id=context.actor_id, timestamp=datetime.now(timezone.utc), metadata={"workflow_id": workflow.id, "name": workflow.name})
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.workflows.add(workflow, context.organization_id)
                uow.events.append(event)
        return workflow

    def list_workflows(self, context: OrganizationContext) -> list[Workflow]:
        """Return only workflows owned by the authenticated organization context."""
        self._require_ready()
        with self.database.session() as session:
            uow = UnitOfWork(session)
            workflows = uow.workflows.list_for_organization(context.organization_id)
            for workflow in workflows:
                workflow.organization = context.organization
                workflow.events = uow.events.for_aggregate(workflow.id, context.organization_id)
            return workflows

    def get_workflow(self, context: OrganizationContext, workflow_id: str) -> Workflow:
        self._require_ready()
        with self.database.session() as session:
            uow = UnitOfWork(session)
            workflow = uow.workflows.get_for_organization(workflow_id, context.organization_id)
            if workflow is None:
                raise NotFoundError(f"Workflow not found: {workflow_id}")
            workflow.organization = context.organization
            workflow.events = uow.events.for_aggregate(workflow_id, context.organization_id)
            return workflow

    def transition_workflow(self, context: OrganizationContext, workflow_id: str, new_state: WorkflowState, evidence: Optional[dict] = None) -> Workflow:
        """Compatibility transition path routed through the canonical command boundary."""
        self._require_ready()
        command_request = AdvanceWorkflowCommand(
            command_id=f"legacy-transition-{uuid4()}",
            organization_id=context.organization_id,
            workflow_id=workflow_id,
            target_state=new_state,
        )
        return self.execute_command(context, command_request).workflow

    def execute_command(self, context: OrganizationContext, command_request: AdvanceWorkflowCommand) -> CommandResult:
        """Execute a command atomically, enforcing central authorization before mutation."""
        self._require_ready()
        if command_request.organization_id != context.organization_id:
            with self.database.session() as session:
                with UnitOfWork(session) as uow:
                    res_org_id = uow.workflows.get_organization_id(command_request.workflow_id)
            decision = AuthorizationDecision(allowed=False, reason="Command organization does not match runtime context", reason_code="command_organization_mismatch", actor_id=context.actor_id, principal_id=context.principal.id, organization_id=context.organization_id, capability_id="workflow.transition", resource_id=command_request.workflow_id, resource_organization_id=res_org_id or context.organization_id)
            self._record_denied_authorization_audit(decision, command_request)
            raise CommandAuthorizationError(decision)
        for attempt in range(_COMMAND_RETRY_LIMIT):
            try:
                return self._execute_command_once(context, command_request)
            except (IntegrityError, RepositoryError) as exc:
                if attempt == _COMMAND_RETRY_LIMIT - 1:
                    raise
                if isinstance(exc, IntegrityError) and ("domain_events.aggregate_id, domain_events.sequence" not in str(exc) and "command_executions" not in str(exc) and "UNIQUE constraint failed" not in str(exc)):
                    raise
                if isinstance(exc, RepositoryError) and "revision conflict" not in str(exc):
                    raise
                sleep(_COMMAND_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError("Unreachable command execution retry state")

    def _record_denied_authorization_audit(self, decision: AuthorizationDecision, command_request: AdvanceWorkflowCommand) -> None:
        audit_event = create_authorization_audit_event(decision, command_id=command_request.command_id, command_type=type(command_request).__name__, allowed=False)
        with self.database.session() as audit_session:
            with UnitOfWork(audit_session) as audit_uow:
                audit_uow.events.append(audit_event)

    def _execute_command_once(self, context: OrganizationContext, command_request: AdvanceWorkflowCommand) -> CommandResult:
        denied_decision: AuthorizationDecision | None = None
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                resource_organization_id = uow.workflows.get_organization_id(command_request.workflow_id)
                decision = AuthorizationService(uow).authorize(principal=context.principal, actor_id=context.actor_id, organization_id=context.organization_id, capability_id="workflow.transition", resource_id=command_request.workflow_id, resource_organization_id=resource_organization_id)
                if not decision.allowed:
                    denied_decision = decision
                else:
                    existing = uow.commands.get(command_request.command_id)
                    if existing is not None:
                        if existing.organization_id != context.organization_id or existing.actor_id != context.actor_id or existing.command_type != type(command_request).__name__ or existing.payload != command_request.payload:
                            raise CommandConflictError(f"Command ID already used with different command data: {command_request.command_id}")
                        workflow = uow.workflows.get_for_organization(command_request.workflow_id, context.organization_id)
                        if workflow is None:
                            raise NotFoundError(f"Workflow not found: {command_request.workflow_id}")
                        workflow.organization = context.organization
                        return CommandResult(command_id=command_request.command_id, workflow=workflow)
                    workflow = uow.workflows.get_for_organization(command_request.workflow_id, context.organization_id)
                    if workflow is None:
                        raise NotFoundError(f"Workflow not found: {command_request.workflow_id}")
                    workflow.organization = context.organization
                    revision = uow.workflows.get_revision(command_request.workflow_id, context.organization_id)
                    if revision is None:
                        raise NotFoundError(f"Workflow not found: {command_request.workflow_id}")
                    audit_event = create_authorization_audit_event(decision, command_id=command_request.command_id, command_type=type(command_request).__name__, allowed=True)
                    uow.events.append(audit_event)
                    try:
                        events = workflow.transition_to(command_request.target_state, context.actor)
                    except InvalidTransitionError:
                        current_state = workflow.current_state.name if workflow.current_state else None
                        if current_state == command_request.target_state:
                            events = []
                        else:
                            raise
                    for event in events:
                        workflow.apply_event(event)
                        uow.events.append(event)
                    uow.workflows.update(workflow, context.organization_id, expected_revision=revision)
                    uow.commands.add(command_id=command_request.command_id, organization_id=context.organization_id, actor_id=context.actor_id, command_type=type(command_request).__name__, payload=command_request.payload, aggregate_id=workflow.id, created_at=datetime.now(timezone.utc))
                    return CommandResult(command_id=command_request.command_id, workflow=workflow)
        if denied_decision is not None:
            self._record_denied_authorization_audit(denied_decision, command_request)
            raise CommandAuthorizationError(denied_decision)
        raise RuntimeError("Command execution completed without a result")

    def get_events(self, context: OrganizationContext, aggregate_id: str, *, include_authorization_audit: bool = False) -> list[Event]:
        self._require_ready()
        with self.database.session() as session:
            events = UnitOfWork(session).events.for_aggregate(aggregate_id, context.organization_id)
        if include_authorization_audit:
            return events
        filtered = [event for event in events if event.event_type not in {EventType.AUTHORIZATION_GRANTED, EventType.AUTHORIZATION_DENIED}]
        for sequence, event in enumerate(filtered, start=1):
            event.sequence = sequence
        return filtered

    @staticmethod
    def _new_workflow(name: str, description: str, organization: Organization) -> Workflow:
        workflow = Workflow(id=str(uuid4()), name=name, description=description, organization=organization)
        transitions = [(WorkflowState.NEW, WorkflowState.ANALYSIS), (WorkflowState.ANALYSIS, WorkflowState.DESIGN), (WorkflowState.DESIGN, WorkflowState.IMPLEMENTATION), (WorkflowState.IMPLEMENTATION, WorkflowState.REVIEW), (WorkflowState.REVIEW, WorkflowState.APPROVED), (WorkflowState.APPROVED, WorkflowState.RELEASED), (WorkflowState.REVIEW, WorkflowState.REJECTED), (WorkflowState.REJECTED, WorkflowState.ANALYSIS), (WorkflowState.RELEASED, WorkflowState.ARCHIVED)]
        for from_state, to_state in transitions:
            workflow.add_transition(Transition(from_state=from_state, to_state=to_state))
        return workflow
