"""Repository implementations for Phase 1 aggregates and events."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.actor import Actor, ActorType
from domain.event import Event, EventType
from domain.organization import Organization
from domain.project import Project, ProjectIntent, ProjectStatus
from domain.workflow import Gate, State, Transition, Workflow, WorkflowState, WorkflowStatus

from .models import (
    ActorModel,
    EventModel,
    OrganizationModel,
    ProjectModel,
    WorkflowModel,
)


class RepositoryError(RuntimeError):
    """Base persistence error."""


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, organization: Organization) -> None:
        self.session.add(
            OrganizationModel(
                id=organization.id,
                name=organization.name,
                description=organization.description,
                created_at=organization.created_at,
                updated_at=organization.updated_at,
            )
        )

    def get(self, organization_id: str) -> Optional[Organization]:
        row = self.session.get(OrganizationModel, organization_id)
        if row is None:
            return None
        return Organization(
            id=row.id,
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ActorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, actor: Actor, organization_id: str) -> None:
        self.session.add(
            ActorModel(
                id=actor.id,
                organization_id=organization_id,
                actor_type=actor.type.name,
                identity=actor.identity,
                status=actor.status,
                created_at=actor.created_at,
                updated_at=actor.updated_at,
            )
        )

    def get_for_organization(self, actor_id: str, organization_id: str) -> Optional[Actor]:
        row = self.session.scalar(
            select(ActorModel).where(
                ActorModel.id == actor_id,
                ActorModel.organization_id == organization_id,
            )
        )
        if row is None:
            return None
        return Actor(
            id=row.id,
            type=ActorType[row.actor_type],
            identity=row.identity,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, workflow: Workflow, organization_id: str) -> None:
        self.session.add(self._to_model(workflow, organization_id, revision=0))

    def get_for_organization(self, workflow_id: str, organization_id: str) -> Optional[Workflow]:
        row = self.session.scalar(
            select(WorkflowModel).where(
                WorkflowModel.id == workflow_id,
                WorkflowModel.organization_id == organization_id,
            )
        )
        if row is None:
            return None
        definition = row.definition
        states = [
            State(
                id=item["id"],
                name=WorkflowState[item["name"]],
                description=item.get("description", ""),
                is_initial=item.get("is_initial", False),
                is_final=item.get("is_final", False),
            )
            for item in definition.get("states", [])
        ]
        transitions = [
            Transition(
                from_state=WorkflowState[item["from_state"]],
                to_state=WorkflowState[item["to_state"]],
                condition=item.get("condition"),
                gate_id=item.get("gate_id"),
                description=item.get("description", ""),
            )
            for item in definition.get("transitions", [])
        ]
        gates = [
            Gate(
                id=item["id"],
                name=item["name"],
                required_approvals=item.get("required_approvals", []),
                min_consensus_score=item.get("min_consensus_score", 0.0),
                conditions=item.get("conditions", {}),
            )
            for item in definition.get("gates", [])
        ]
        workflow = Workflow(
            id=row.id,
            name=row.name,
            description=row.description,
            states=states,
            transitions=transitions,
            gates=gates,
            status=WorkflowStatus[row.status],
            version=row.version,
            metadata=row.metadata_json,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        workflow.current_state = next(
            (state for state in workflow.states if state.name.name == row.current_state),
            workflow.states[0] if workflow.states else None,
        )
        return workflow

    def get_organization_id(self, workflow_id: str) -> Optional[str]:
        """Resolve only the owning organization of a target resource.

        This is used by the authorization boundary to distinguish a missing
        resource from a cross-organization resource without exposing the
        resource itself to the caller.
        """
        return self.session.scalar(
            select(WorkflowModel.organization_id).where(WorkflowModel.id == workflow_id)
        )

    def get_revision(self, workflow_id: str, organization_id: str) -> Optional[int]:
        return self.session.scalar(
            select(WorkflowModel.revision).where(
                WorkflowModel.id == workflow_id,
                WorkflowModel.organization_id == organization_id,
            )
        )

    def update(self, workflow: Workflow, organization_id: str, expected_revision: int) -> None:
        row = self.session.scalar(
            select(WorkflowModel).where(
                WorkflowModel.id == workflow.id,
                WorkflowModel.organization_id == organization_id,
                WorkflowModel.revision == expected_revision,
            )
        )
        if row is None:
            raise RepositoryError("Workflow not found or revision conflict")
        row.name = workflow.name
        row.description = workflow.description
        row.version = workflow.version
        row.status = workflow.status.name
        row.current_state = workflow.current_state.name.name if workflow.current_state else None
        row.definition = self._definition(workflow)
        row.metadata_json = workflow.metadata
        row.updated_at = workflow.updated_at
        row.revision = expected_revision + 1
        self.session.flush()

    @staticmethod
    def _definition(workflow: Workflow) -> dict:
        return {
            "states": [
                {
                    "id": state.id,
                    "name": state.name.name,
                    "description": state.description,
                    "is_initial": state.is_initial,
                    "is_final": state.is_final,
                }
                for state in workflow.states
            ],
            "transitions": [
                {
                    "from_state": transition.from_state.name,
                    "to_state": transition.to_state.name,
                    "condition": transition.condition,
                    "gate_id": transition.gate_id,
                    "description": transition.description,
                }
                for transition in workflow.transitions
            ],
            "gates": [
                {
                    "id": gate.id,
                    "name": gate.name,
                    "required_approvals": gate.required_approvals,
                    "min_consensus_score": gate.min_consensus_score,
                    "conditions": gate.conditions,
                }
                for gate in workflow.gates
            ],
        }

    def _to_model(self, workflow: Workflow, organization_id: str, revision: int) -> WorkflowModel:
        return WorkflowModel(
            id=workflow.id,
            organization_id=organization_id,
            name=workflow.name,
            description=workflow.description,
            version=workflow.version,
            status=workflow.status.name,
            current_state=workflow.current_state.name.name if workflow.current_state else None,
            definition=self._definition(workflow),
            metadata_json=workflow.metadata,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            revision=revision,
        )


class ProjectRepository:
    """Organization-scoped durable project storage with integrity checks."""

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
            required_capabilities=tuple(
                row.intent.get("required_capabilities", [])
            ),
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
            revision=row.revision,
            contract_version=row.contract_version,
        )


class EventStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: Event) -> Event:
        max_sequence = self.session.scalar(
            select(func.max(EventModel.sequence)).where(
                EventModel.aggregate_id == event.aggregate_id,
                EventModel.organization_id == event.organization_id,
            )
        )
        event.sequence = (max_sequence or 0) + 1
        self.session.add(
            EventModel(
                id=event.id,
                event_type=event.event_type.name,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                organization_id=event.organization_id,
                actor_id=event.actor_id,
                timestamp=event.timestamp,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                event_metadata=event.metadata,
                schema_version=event.schema_version,
                sequence=event.sequence,
            )
        )
        self.session.flush()
        return event

    def for_aggregate(self, aggregate_id: str, organization_id: str) -> list[Event]:
        rows = self.session.scalars(
            select(EventModel)
            .where(
                EventModel.aggregate_id == aggregate_id,
                EventModel.organization_id == organization_id,
            )
            .order_by(EventModel.sequence)
        ).all()
        return [
            Event(
                id=row.id,
                event_type=EventType[row.event_type],
                aggregate_id=row.aggregate_id,
                aggregate_type=row.aggregate_type,
                organization_id=row.organization_id,
                actor_id=row.actor_id,
                timestamp=row.timestamp,
                correlation_id=row.correlation_id,
                causation_id=row.causation_id,
                metadata=row.event_metadata,
                schema_version=row.schema_version,
                sequence=row.sequence,
            )
            for row in rows
        ]
