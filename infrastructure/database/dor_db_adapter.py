# infrastructure/database/dor_db_adapter.py
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from domain.organization import Organization
from domain.actor import Actor, ActorType
from domain.role_definition import RoleDefinition
from domain.capability import Capability, CapabilityLevel
from domain.intent import Intent, IntentPriority
from domain.workflow import Workflow, WorkflowState, State, Transition, Gate
from domain.task import Task, TaskStatus, TaskPriority
from domain.artifact import Artifact, ArtifactState, ArtifactType
from domain.event import Event, EventType
from domain.policy import Policy
from domain.governance import GovernanceDepartment
from .unit_of_work import UnitOfWork
from .models import (
    OrganizationModel, DepartmentModel, TeamModel, ActorModel,
    RoleDefinitionModel, CapabilityModel, IntentModel, WorkflowModel,
    TaskModel, ArtifactModel, SignatureModel, EventModel, PolicyModel,
    GovernanceDepartmentModel
)

class DORDBAdapter:
    """Adapter til at konvertere mellem domæneobjekter og database-modeller."""

    def __init__(self, db: Session):
        self.db = db
        self.uow = UnitOfWork(db)

    # --- Organization ---
    def create_organization(self, organization: Organization) -> OrganizationModel:
        """Opret en Organization i databasen."""
        org_model = self.uow.organization.create(
            id=organization.id,
            name=organization.name,
            description=organization.description
        )
        return org_model

    def get_organization(self, organization_id: str) -> Optional[Organization]:
        """Hent en Organization fra databasen."""
        org_model = self.uow.organization.get(organization_id)
        if not org_model:
            return None
        return Organization(
            id=org_model.id,
            name=org_model.name,
            description=org_model.description
        )

    # --- Actor ---
    def create_actor(self, actor: Actor) -> ActorModel:
        """Opret en Actor i databasen."""
        actor_model = self.uow.actor.create(
            id=actor.id,
            type=actor.type,
            identity=actor.identity,
            status=actor.status,
            organization_id=actor.organization.id if actor.organization else None,
            department_id=actor.department.id if actor.department else None,
            team_id=actor.team.id if actor.team else None,
            role_id=actor.role.id if actor.role else None
        )
        # Tilføj Capabilities (mange-til-mange)
        for cap in actor.capabilities:
            self.uow.db.execute(
                "INSERT INTO actor_capability (actor_id, capability_id) VALUES (:actor_id, :capability_id)",
                {"actor_id": actor_model.id, "capability_id": cap.id}
            )
        self.uow.commit()
        return actor_model

    def get_actor(self, actor_id: str) -> Optional[Actor]:
        """Hent en Actor fra databasen."""
        actor_model = self.uow.actor.get(actor_id)
        if not actor_model:
            return None

        # Hent relaterede objekter
        role = self.get_role_definition(actor_model.role_id) if actor_model.role_id else None
        capabilities = self.uow.capability.get_all()
        actor_capabilities = [
            cap for cap in capabilities
            if cap.id in [c.id for c in actor_model.capabilities]
        ]

        return Actor(
            id=actor_model.id,
            type=actor_model.type,
            identity=actor_model.identity,
            status=actor_model.status,
            role=role,
            capabilities=actor_capabilities
        )

    # --- RoleDefinition ---
    def create_role_definition(self, role: RoleDefinition) -> RoleDefinitionModel:
        """Opret en RoleDefinition i databasen."""
        role_model = self.uow.role_definition.create(
            id=role.id,
            name=role.name,
            description=role.description,
            authority=role.authority,
            needs_approval_from=role.needs_approval_from,
            responsibilities=role.responsibilities,
            organization_id=role.organization.id if role.organization else None,
            department_id=role.department_id,
            team_id=role.team_id
        )
        return role_model

    def get_role_definition(self, role_id: str) -> Optional[RoleDefinition]:
        """Hent en RoleDefinition fra databasen."""
        role_model = self.uow.role_definition.get(role_id)
        if not role_model:
            return None
        return RoleDefinition(
            id=role_model.id,
            name=role_model.name,
            description=role_model.description,
            authority=role_model.authority,
            needs_approval_from=role_model.needs_approval_from,
            responsibilities=role_model.responsibilities
        )

    # --- Capability ---
    def create_capability(self, capability: Capability) -> CapabilityModel:
        """Opret en Capability i databasen."""
        cap_model = self.uow.capability.create(
            id=capability.id,
            name=capability.name,
            description=capability.description,
            level=capability.level,
            certification=capability.certification
        )
        return cap_model

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Hent en Capability fra databasen."""
        cap_model = self.uow.capability.get(capability_id)
        if not cap_model:
            return None
        return Capability(
            id=cap_model.id,
            name=cap_model.name,
            description=cap_model.description,
            level=cap_model.level,
            certification=cap_model.certification
        )

    # --- Intent ---
    def create_intent(self, intent: Intent) -> IntentModel:
        """Opret en Intent i databasen."""
        intent_model = self.uow.intent.create(
            id=intent.id,
            goal=intent.goal,
            description=intent.description,
            priority=intent.priority,
            constraints=intent.constraints,
            required_capabilities=intent.required_capabilities,
            creator_id=intent.creator.id if intent.creator else None,
            organization_id=intent.organization.id if intent.organization else None
        )
        return intent_model

    def get_intent(self, intent_id: str) -> Optional[Intent]:
        """Hent en Intent fra databasen."""
        intent_model = self.uow.intent.get(intent_id)
        if not intent_model:
            return None

        creator = self.get_actor(intent_model.creator_id) if intent_model.creator_id else None
        organization = self.get_organization(intent_model.organization_id) if intent_model.organization_id else None

        return Intent(
            id=intent_model.id,
            goal=intent_model.goal,
            description=intent_model.description,
            priority=intent_model.priority,
            constraints=intent_model.constraints,
            required_capabilities=intent_model.required_capabilities,
            creator=creator,
            organization=organization
        )

    # --- Workflow ---
    def create_workflow(self, workflow: Workflow) -> WorkflowModel:
        """Opret et Workflow i databasen."""
        workflow_model = self.uow.workflow.create(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            current_state=workflow.current_state.name if workflow.current_state else None,
            intent_id=workflow.intent.id if workflow.intent else None,
            organization_id=workflow.organization.id if workflow.organization else None
        )

        # Tilføj States
        for state in workflow.states:
            self.uow.db.execute(
                "INSERT INTO workflow_states (workflow_id, id, name, description) VALUES (:workflow_id, :id, :name, :description)",
                {
                    "workflow_id": workflow_model.id,
                    "id": state.id,
                    "name": state.name.value,
                    "description": state.description
                }
            )

        # Tilføj Transitions
        for transition in workflow.transitions:
            self.uow.db.execute(
                "INSERT INTO workflow_transitions (workflow_id, from_state, to_state, condition, gate) VALUES (:workflow_id, :from_state, :to_state, :condition, :gate)",
                {
                    "workflow_id": workflow_model.id,
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "condition": transition.condition,
                    "gate": transition.gate
                }
            )

        # Tilføj Gates
        for gate in workflow.gates:
            self.uow.db.execute(
                "INSERT INTO workflow_gates (workflow_id, id, name, required_approvals, min_consensus_score, conditions) VALUES (:workflow_id, :id, :name, :required_approvals, :min_consensus_score, :conditions)",
                {
                    "workflow_id": workflow_model.id,
                    "id": gate.id,
                    "name": gate.name,
                    "required_approvals": str(gate.required_approvals),
                    "min_consensus_score": gate.min_consensus_score,
                    "conditions": str(gate.conditions)
                }
            )

        self.uow.commit()
        return workflow_model

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Hent et Workflow fra databasen."""
        workflow_model = self.uow.workflow.get(workflow_id)
        if not workflow_model:
            return None

        # Hent States
        states_result = self.uow.db.execute(
            "SELECT id, name, description FROM workflow_states WHERE workflow_id = :workflow_id",
            {"workflow_id": workflow_id}
        ).fetchall()
        states = [
            State(id=row.id, name=WorkflowState(row.name), description=row.description)
            for row in states_result
        ]

        # Hent Transitions
        transitions_result = self.uow.db.execute(
            "SELECT from_state, to_state, condition, gate FROM workflow_transitions WHERE workflow_id = :workflow_id",
            {"workflow_id": workflow_id}
        ).fetchall()
        transitions = [
            Transition(
                from_state=row.from_state,
                to_state=row.to_state,
                condition=row.condition,
                gate=row.gate
            )
            for row in transitions_result
        ]

        # Hent Gates
        gates_result = self.uow.db.execute(
            "SELECT id, name, required_approvals, min_consensus_score, conditions FROM workflow_gates WHERE workflow_id = :workflow_id",
            {"workflow_id": workflow_id}
        ).fetchall()
        gates = [
            Gate(
                id=row.id,
                name=row.name,
                required_approvals=eval(row.required_approvals) if row.required_approvals else [],
                min_consensus_score=row.min_consensus_score,
                conditions=eval(row.conditions) if row.conditions else {}
            )
            for row in gates_result
        ]

        # Hent Intent
        intent = self.get_intent(workflow_model.intent_id) if workflow_model.intent_id else None

        # Hent Organization
        organization = self.get_organization(workflow_model.organization_id) if workflow_model.organization_id else None

        # Find current_state
        current_state = next(
            (s for s in states if s.name.value == workflow_model.current_state),
            None
        )

        return Workflow(
            id=workflow_model.id,
            name=workflow_model.name,
            description=workflow_model.description,
            states=states,
            transitions=transitions,
            gates=gates,
            current_state=current_state,
            intent=intent,
            organization=organization
        )

    # --- Task ---
    def create_task(self, task: Task) -> TaskModel:
        """Opret en Task i databasen."""
        task_model = self.uow.task.create(
            id=task.id,
            name=task.name,
            description=task.description,
            status=task.status,
            priority=task.priority,
            metadata=task.metadata,
            workflow_id=task.workflow_id,
            assigned_actor_id=task.assigned_actor.id if task.assigned_actor else None,
            dependencies=task.dependencies,
            input_artifacts=task.input_artifacts,
            output_artifacts=task.output_artifacts
        )
        return task_model

    def get_task(self, task_id: str) -> Optional[Task]:
        """Hent en Task fra databasen."""
        task_model = self.uow.task.get(task_id)
        if not task_model:
            return None

        workflow = self.get_workflow(task_model.workflow_id) if task_model.workflow_id else None
        assigned_actor = self.get_actor(task_model.assigned_actor_id) if task_model.assigned_actor_id else None

        return Task(
            id=task_model.id,
            name=task_model.name,
            description=task_model.description,
            status=task_model.status,
            priority=task_model.priority,
            workflow_id=task_model.workflow_id,
            assigned_actor=assigned_actor,
            dependencies=task_model.dependencies,
            input_artifacts=task_model.input_artifacts,
            output_artifacts=task_model.output_artifacts,
            metadata=task_model.metadata
        )

    # --- Artifact ---
    def create_artifact(self, artifact: Artifact) -> ArtifactModel:
        """Opret et Artifact i databasen."""
        artifact_model = self.uow.artifact.create(
            id=artifact.id,
            version=artifact.version,
            artifact_type=artifact.artifact_type,
            hash=artifact.hash,
            state=artifact.state,
            metadata=artifact.metadata,
            owner_id=artifact.owner.id if artifact.owner else None,
            department_id=artifact.department_id,
            workflow_id=artifact.workflow_id
        )

        # Tilføj Signatures
        for sig in artifact.signatures:
            self.uow.db.execute(
                "INSERT INTO signatures (id, role_id, actor_id, status, comments, artifact_id) VALUES (:id, :role_id, :actor_id, :status, :comments, :artifact_id)",
                {
                    "id": sig.id,
                    "role_id": sig.role_id,
                    "actor_id": sig.actor_id,
                    "status": sig.status,
                    "comments": sig.comments,
                    "artifact_id": artifact_model.id
                }
            )

        # Tilføj Parent/Child relationer
        for parent_id in artifact.parents:
            self.uow.db.execute(
                "INSERT INTO artifact_parent (artifact_id, parent_id) VALUES (:artifact_id, :parent_id)",
                {"artifact_id": artifact_model.id, "parent_id": parent_id}
            )

        self.uow.commit()
        return artifact_model

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Hent et Artifact fra databasen."""
        artifact_model = self.uow.artifact.get(artifact_id)
        if not artifact_model:
            return None

        # Hent Signatures
        signatures_result = self.uow.db.execute(
            "SELECT id, role_id, actor_id, status, comments FROM signatures WHERE artifact_id = :artifact_id",
            {"artifact_id": artifact_id}
        ).fetchall()
        signatures = [
            Signature(
                id=row.id,
                role_id=row.role_id,
                actor_id=row.actor_id,
                status=row.status,
                comments=row.comments
            )
            for row in signatures_result
        ]

        # Hent Parents
        parents_result = self.uow.db.execute(
            "SELECT parent_id FROM artifact_parent WHERE artifact_id = :artifact_id",
            {"artifact_id": artifact_id}
        ).fetchall()
        parents = [row.parent_id for row in parents_result]

        # Hent Children
        children_result = self.uow.db.execute(
            "SELECT artifact_id FROM artifact_parent WHERE parent_id = :parent_id",
            {"parent_id": artifact_id}
        ).fetchall()
        children = [row.artifact_id for row in children_result]

        # Hent Owner
        owner = self.get_actor(artifact_model.owner_id) if artifact_model.owner_id else None

        # Hent Workflow
        workflow = self.get_workflow(artifact_model.workflow_id) if artifact_model.workflow_id else None

        return Artifact(
            id=artifact_model.id,
            version=artifact_model.version,
            artifact_type=artifact_model.artifact_type,
            hash=artifact_model.hash,
            state=artifact_model.state,
            owner=owner,
            department_id=artifact_model.department_id,
            workflow_id=artifact_model.workflow_id,
            signatures=signatures,
            parents=parents,
            children=children,
            metadata=artifact_model.metadata
        )

    # --- Event ---
    def create_event(self, event: Event) -> EventModel:
        """Opret et Event i databasen."""
        event_model = self.uow.event.create(
            id=event.id,
            event_type=event.event_type,
            metadata=event.metadata,
            actor_id=event.actor.id if event.actor else None,
            workflow_id=event.workflow.id if event.workflow else None,
            artifact_id=event.artifact.id if event.artifact else None,
            timestamp=event.timestamp
        )
        return event_model

    def get_event(self, event_id: str) -> Optional[Event]:
        """Hent et Event fra databasen."""
        event_model = self.uow.event.get(event_id)
        if not event_model:
            return None

        actor = self.get_actor(event_model.actor_id) if event_model.actor_id else None
        workflow = self.get_workflow(event_model.workflow_id) if event_model.workflow_id else None
        artifact = self.get_artifact(event_model.artifact_id) if event_model.artifact_id else None

        return Event(
            id=event_model.id,
            event_type=event_model.event_type,
            actor=actor,
            workflow=workflow,
            artifact=artifact,
            metadata=event_model.metadata,
            timestamp=event_model.timestamp
        )

    # --- Policy ---
    def create_policy(self, policy: Policy) -> PolicyModel:
        """Opret en Policy i databasen."""
        policy_model = self.uow.policy.create(
            id=policy.id,
            name=policy.name,
            description=policy.description,
            scope=policy.scope,
            conditions=policy.conditions,
            actions=policy.actions,
            organization_id=policy.organization.id if policy.organization else None,
            department_id=policy.department_id
        )
        return policy_model

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Hent en Policy fra databasen."""
        policy_model = self.uow.policy.get(policy_id)
        if not policy_model:
            return None
        return Policy(
            id=policy_model.id,
            name=policy_model.name,
            description=policy_model.description,
            scope=policy_model.scope,
            conditions=policy_model.conditions,
            actions=policy_model.actions
        )

    # --- GovernanceDepartment ---
    def create_governance(self, governance: GovernanceDepartment) -> GovernanceDepartmentModel:
        """Opret et GovernanceDepartment i databasen."""
        governance_model = self.uow.governance.create(
            id=governance.id,
            name=governance.name,
            organization_id=governance.organization.id if governance.organization else None
        )

        # Tilføj Boards
        for board_name in ["architecture", "security", "compliance", "quality"]:
            board = getattr(governance, f"{board_name}_board", [])
            for actor in board:
                self.uow.db.execute(
                    f"INSERT INTO {board_name}_board (governance_id, actor_id) VALUES (:governance_id, :actor_id)",
                    {"governance_id": governance_model.id, "actor_id": actor.id}
                )

        self.uow.commit()
        return governance_model

    def get_governance(self, governance_id: str) -> Optional[GovernanceDepartment]:
        """Hent et GovernanceDepartment fra databasen."""
        governance_model = self.uow.governance.get(governance_id)
        if not governance_model:
            return None

        # Hent Boards
        boards = {}
        for board_name in ["architecture", "security", "compliance", "quality"]:
            board_result = self.uow.db.execute(
                f"SELECT actor_id FROM {board_name}_board WHERE governance_id = :governance_id",
                {"governance_id": governance_id}
            ).fetchall()
            boards[board_name] = [
                self.get_actor(row.actor_id) for row in board_result
            ]

        # Hent Organization
        organization = self.get_organization(governance_model.organization_id) if governance_model.organization_id else None

        return GovernanceDepartment(
            id=governance_model.id,
            name=governance_model.name,
            organization=organization,
            architecture_board=boards.get("architecture", []),
            security_board=boards.get("security", []),
            compliance_board=boards.get("compliance", []),
            quality_board=boards.get("quality", [])
        )
