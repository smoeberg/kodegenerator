"""Repository implementations for Phase 1 aggregates and events."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.actor import Actor, ActorType
from domain.event import Event, EventType
from domain.organization import Organization
from domain.workflow import Gate, State, Transition, Workflow, WorkflowState, WorkflowStatus

from .models import ActorModel, EventModel, OrganizationModel, WorkflowModel


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


class EventStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: Event) -> Event:
        max_sequence = self.session.scalar(
            select(func.max(EventModel.sequence)).where(EventModel.aggregate_id == event.aggregate_id)
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
