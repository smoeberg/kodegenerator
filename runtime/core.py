"""Phase 1 DOR runtime: boot, identity context, workflow and durable events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from domain.actor import Actor
from domain.event import Event, EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import Transition, Workflow, WorkflowState

from infrastructure.persistence.database import Database
from infrastructure.persistence.models import Base
from infrastructure.persistence.repositories import RepositoryError
from infrastructure.persistence.uow import UnitOfWork
from .context import ContextError, OrganizationContext, establish_context


class RuntimeNotReadyError(RuntimeError):
    """Raised when runtime work is attempted before boot."""


class NotFoundError(RuntimeError):
    """Raised when an organization-scoped resource does not exist."""


class DORRuntime:
    """Minimal, persistent Phase 1 runtime vertical slice."""

    def __init__(self, database_url: str = "sqlite:///./dor_runtime.db") -> None:
        self.database = Database(database_url)
        self.ready = False

    def boot(self) -> None:
        """Initialize the schema and mark the runtime ready.

        Phase 1 uses SQLAlchemy metadata as the bootstrap schema authority. A
        dedicated migration runner can be introduced without changing the
        repository/application contracts once the schema is stabilized.
        """
        Base.metadata.create_all(self.database.engine)
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
        event = Event(
            event_type=EventType.WORKFLOW_CREATED,
            aggregate_id=workflow.id,
            aggregate_type="workflow",
            organization_id=context.organization_id,
            actor_id=context.actor_id,
            timestamp=datetime.now(timezone.utc),
            metadata={"workflow_id": workflow.id, "name": workflow.name},
        )
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                uow.workflows.add(workflow, context.organization_id)
                uow.events.append(event)
        return workflow

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

    def transition_workflow(
        self,
        context: OrganizationContext,
        workflow_id: str,
        new_state: WorkflowState,
        evidence: Optional[dict] = None,
    ) -> Workflow:
        """Execute one workflow transition atomically with its event."""
        self._require_ready()
        with self.database.session() as session:
            with UnitOfWork(session) as uow:
                workflow = uow.workflows.get_for_organization(workflow_id, context.organization_id)
                if workflow is None:
                    raise NotFoundError(f"Workflow not found: {workflow_id}")
                workflow.organization = context.organization
                revision = uow.workflows.get_revision(workflow_id, context.organization_id)
                if revision is None:
                    raise NotFoundError(f"Workflow not found: {workflow_id}")

                events = workflow.transition_to(new_state, context.actor, evidence=evidence)
                for event in events:
                    workflow.apply_event(event)
                    uow.events.append(event)
                uow.workflows.update(workflow, context.organization_id, expected_revision=revision)
                return workflow

    def get_events(self, context: OrganizationContext, aggregate_id: str) -> list[Event]:
        self._require_ready()
        with self.database.session() as session:
            return UnitOfWork(session).events.for_aggregate(aggregate_id, context.organization_id)

    @staticmethod
    def _new_workflow(name: str, description: str, organization: Organization) -> Workflow:
        workflow = Workflow(
            id=str(uuid4()),
            name=name,
            description=description,
            organization=organization,
        )
        transitions = [
            (WorkflowState.NEW, WorkflowState.ANALYSIS),
            (WorkflowState.ANALYSIS, WorkflowState.DESIGN),
            (WorkflowState.DESIGN, WorkflowState.IMPLEMENTATION),
            (WorkflowState.IMPLEMENTATION, WorkflowState.REVIEW),
            (WorkflowState.REVIEW, WorkflowState.APPROVED),
            (WorkflowState.APPROVED, WorkflowState.RELEASED),
            (WorkflowState.REVIEW, WorkflowState.REJECTED),
            (WorkflowState.REJECTED, WorkflowState.ANALYSIS),
            (WorkflowState.RELEASED, WorkflowState.ARCHIVED),
        ]
        for from_state, to_state in transitions:
            workflow.add_transition(Transition(from_state=from_state, to_state=to_state))
        return workflow
