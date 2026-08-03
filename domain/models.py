# infrastructure/database/models.py
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, Enum, Table
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum as PyEnum
import uuid

# Base-klasse for SQLAlchemy-modeller
Base = declarative_base()

# --- Enum-typer (til SQLAlchemy) ---
class ActorType(PyEnum):
    HUMAN = "human"
    DIGITAL_EMPLOYEE = "digital_employee"
    SERVICE = "service"
    EXTERNAL = "external"

class WorkflowState(PyEnum):
    NEW = "new"
    ANALYSIS = "analysis"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    APPROVED = "approved"
    RELEASED = "released"
    REJECTED = "rejected"
    ARCHIVED = "archived"

class ArtifactState(PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RELEASED = "released"
    ARCHIVED = "archived"

class ArtifactType(PyEnum):
    SPECIFICATION = "specification"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    DECISION = "decision"
    RELEASE = "release"
    LEGAL = "legal"
    FINANCIAL = "financial"

class TaskStatus(PyEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(PyEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

class CapabilityLevel(PyEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"

class IntentPriority(PyEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

class EventType(PyEnum):
    INTENT_CREATED = "intent_created"
    WORKFLOW_STARTED = "workflow_started"
    STATE_CHANGED = "state_changed"
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_APPROVED = "artifact_approved"
    ARTIFACT_REJECTED = "artifact_rejected"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    POLICY_VIOLATED = "policy_violated"
    GOVERNANCE_APPROVAL = "governance_approval"
    MODEL_SWAPPED = "model_swapped"

# --- Association Tables (Mange-til-mange relationer) ---
# Actor <-> Capability
actor_capability = Table(
    "actor_capability",
    Base.metadata,
    Column("actor_id", String, ForeignKey("actors.id"), primary_key=True),
    Column("capability_id", String, ForeignKey("capabilities.id"), primary_key=True),
)

# Actor <-> RoleDefinition
actor_role = Table(
    "actor_role",
    Base.metadata,
    Column("actor_id", String, ForeignKey("actors.id"), primary_key=True),
    Column("role_id", String, ForeignKey("role_definitions.id"), primary_key=True),
)

# Workflow <-> Task
workflow_task = Table(
    "workflow_task",
    Base.metadata,
    Column("workflow_id", String, ForeignKey("workflows.id"), primary_key=True),
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
)

# Artifact <-> Parent/Child (for versionering)
artifact_parent = Table(
    "artifact_parent",
    Base.metadata,
    Column("artifact_id", String, ForeignKey("artifacts.id"), primary_key=True),
    Column("parent_id", String, ForeignKey("artifacts.id"), primary_key=True),
)

# --- SQLAlchemy-modeller ---
class OrganizationModel(Base):
    __tablename__ = "organizations"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    departments = relationship("DepartmentModel", back_populates="organization", cascade="all, delete-orphan")
    actors = relationship("ActorModel", back_populates="organization", cascade="all, delete-orphan")
    policies = relationship("PolicyModel", back_populates="organization", cascade="all, delete-orphan")
    governance = relationship("GovernanceDepartmentModel", back_populates="organization", uselist=False, cascade="all, delete-orphan")

class DepartmentModel(Base):
    __tablename__ = "departments"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    budget = Column(Float, default=0.0)
    manager_id = Column(String(36), ForeignKey("actors.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    organization = relationship("OrganizationModel", back_populates="departments")
    teams = relationship("TeamModel", back_populates="department", cascade="all, delete-orphan")
    actors = relationship("ActorModel", back_populates="department")
    policies = relationship("PolicyModel", back_populates="department")

class TeamModel(Base):
    __tablename__ = "teams"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    lead_id = Column(String(36), ForeignKey("actors.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    department_id = Column(String(36), ForeignKey("departments.id"))
    department = relationship("DepartmentModel", back_populates="teams")
    members = relationship("ActorModel", back_populates="team")

class ActorModel(Base):
    __tablename__ = "actors"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(Enum(ActorType), nullable=False)
    identity = Column(String(100), nullable=False)  # f.eks. "GPT-5", "John Doe"
    status = Column(String(20), default="active")  # "active", "inactive", "suspended"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    organization = relationship("OrganizationModel", back_populates="actors")
    department_id = Column(String(36), ForeignKey("departments.id"))
    department = relationship("DepartmentModel", back_populates="actors")
    team_id = Column(String(36), ForeignKey("teams.id"))
    team = relationship("TeamModel", back_populates="members")
    role_id = Column(String(36), ForeignKey("role_definitions.id"))
    role = relationship("RoleDefinitionModel", back_populates="actors")
    capabilities = relationship("CapabilityModel", secondary=actor_capability, back_populates="actors")
    tasks = relationship("TaskModel", back_populates="assigned_actor")
    events = relationship("EventModel", back_populates="actor")

class RoleDefinitionModel(Base):
    __tablename__ = "role_definitions"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    authority = Column(JSON, default={})  # f.eks. {"can_approve": True, "can_reject": False}
    needs_approval_from = Column(JSON, default={})  # f.eks. {"merge_to_main": ["architecture_reviewer"]}
    responsibilities = Column(JSON, default=[])  # Liste af ansvarsområder
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    department_id = Column(String(36), ForeignKey("departments.id"))
    team_id = Column(String(36), ForeignKey("teams.id"))
    actors = relationship("ActorModel", back_populates="role")

class CapabilityModel(Base):
    __tablename__ = "capabilities"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    level = Column(Enum(CapabilityLevel), default=CapabilityLevel.BEGINNER)
    certification = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    actors = relationship("ActorModel", secondary=actor_capability, back_populates="capabilities")

class IntentModel(Base):
    __tablename__ = "intents"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal = Column(String(200), nullable=False)
    description = Column(String(500))
    priority = Column(Enum(IntentPriority), default=IntentPriority.MEDIUM)
    constraints = Column(JSON, default={})
    required_capabilities = Column(JSON, default=[])  # Liste af Capability-ID'er
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    creator_id = Column(String(36), ForeignKey("actors.id"))
    creator = relationship("ActorModel")
    workflow_id = Column(String(36), ForeignKey("workflows.id"))
    workflow = relationship("WorkflowModel", back_populates="intent")
    organization_id = Column(String(36), ForeignKey("organizations.id"))

class WorkflowModel(Base):
    __tablename__ = "workflows"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    current_state = Column(Enum(WorkflowState), default=WorkflowState.NEW)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    intent_id = Column(String(36), ForeignKey("intents.id"))
    intent = relationship("IntentModel", back_populates="workflow")
    tasks = relationship("TaskModel", secondary=workflow_task, back_populates="workflow")
    artifacts = relationship("ArtifactModel", back_populates="workflow")
    events = relationship("EventModel", back_populates="workflow")

class TaskModel(Base):
    __tablename__ = "tasks"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    priority = Column(Enum(TaskPriority), default=TaskPriority.MEDIUM)
    metadata = Column(JSON, default={})  # f.eks. deadline, estimeret tid
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    workflow_id = Column(String(36), ForeignKey("workflows.id"))
    workflow = relationship("WorkflowModel", back_populates="tasks")
    assigned_actor_id = Column(String(36), ForeignKey("actors.id"))
    assigned_actor = relationship("ActorModel", back_populates="tasks")
    dependencies = Column(JSON, default=[])  # Liste af Task-ID'er
    input_artifacts = Column(JSON, default=[])  # Liste af Artefakt-ID'er
    output_artifacts = Column(JSON, default=[])  # Liste af Artefakt-ID'er

class ArtifactModel(Base):
    __tablename__ = "artifacts"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version = Column(String(20), nullable=False)  # f.eks. "1.0.0"
    artifact_type = Column(Enum(ArtifactType), nullable=False)
    hash = Column(String(64))  # SHA-256 hash
    state = Column(Enum(ArtifactState), default=ArtifactState.DRAFT)
    metadata = Column(JSON, default={})  # Specifikke felter (f.eks. code, tests)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    owner_id = Column(String(36), ForeignKey("actors.id"))
    owner = relationship("ActorModel")
    department_id = Column(String(36), ForeignKey("departments.id"))
    workflow_id = Column(String(36), ForeignKey("workflows.id"))
    workflow = relationship("WorkflowModel", back_populates="artifacts")
    signatures = relationship("SignatureModel", back_populates="artifact", cascade="all, delete-orphan")
    parents = relationship(
        "ArtifactModel",
        secondary=artifact_parent,
        primaryjoin="ArtifactModel.id == artifact_parent.c.artifact_id",
        secondaryjoin="ArtifactModel.id == artifact_parent.c.parent_id",
        back_populates="children"
    )
    children = relationship(
        "ArtifactModel",
        secondary=artifact_parent,
        primaryjoin="ArtifactModel.id == artifact_parent.c.parent_id",
        secondaryjoin="ArtifactModel.id == artifact_parent.c.artifact_id",
        back_populates="parents"
    )
    events = relationship("EventModel", back_populates="artifact")

class SignatureModel(Base):
    __tablename__ = "signatures"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_id = Column(String(36))  # Rolle-ID (f.eks. "architecture_reviewer")
    actor_id = Column(String(36), ForeignKey("actors.id"))
    status = Column(String(20), nullable=False)  # "approved", "rejected", "needs_changes"
    comments = Column(String(500))
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationer
    artifact_id = Column(String(36), ForeignKey("artifacts.id"))
    artifact = relationship("ArtifactModel", back_populates="signatures")

class EventModel(Base):
    __tablename__ = "events"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(Enum(EventType), nullable=False)
    metadata = Column(JSON, default={})
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationer
    actor_id = Column(String(36), ForeignKey("actors.id"))
    actor = relationship("ActorModel", back_populates="events")
    workflow_id = Column(String(36), ForeignKey("workflows.id"))
    workflow = relationship("WorkflowModel", back_populates="events")
    artifact_id = Column(String(36), ForeignKey("artifacts.id"))
    artifact = relationship("ArtifactModel", back_populates="events")

class PolicyModel(Base):
    __tablename__ = "policies"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    scope = Column(String(50), default="global")  # "global", "department:<id>", "team:<id>"
    conditions = Column(JSON, default={})  # f.eks. {"min_coverage": 0.9}
    actions = Column(JSON, default={})  # f.eks. {"on_violation": "block"}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    organization = relationship("OrganizationModel", back_populates="policies")
    department_id = Column(String(36), ForeignKey("departments.id"))
    department = relationship("DepartmentModel", back_populates="policies")

class GovernanceDepartmentModel(Base):
    __tablename__ = "governance_departments"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), default="Governance Department")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    organization_id = Column(String(36), ForeignKey("organizations.id"))
    organization = relationship("OrganizationModel", back_populates="governance")
    architecture_board = relationship("ActorModel", secondary="architecture_board", back_populates="governance_boards")
    security_board = relationship("ActorModel", secondary="security_board", back_populates="governance_boards")
    compliance_board = relationship("ActorModel", secondary="compliance_board", back_populates="governance_boards")
    quality_board = relationship("ActorModel", secondary="quality_board", back_populates="governance_boards")

# Association Tables for Governance Boards
architecture_board = Table(
    "architecture_board",
    Base.metadata,
    Column("governance_id", String(36), ForeignKey("governance_departments.id"), primary_key=True),
    Column("actor_id", String(36), ForeignKey("actors.id"), primary_key=True),
)

security_board = Table(
    "security_board",
    Base.metadata,
    Column("governance_id", String(36), ForeignKey("governance_departments.id"), primary_key=True),
    Column("actor_id", String(36), ForeignKey("actors.id"), primary_key=True),
)

compliance_board = Table(
    "compliance_board",
    Base.metadata,
    Column("governance_id", String(36), ForeignKey("governance_departments.id"), primary_key=True),
    Column("actor_id", String(36), ForeignKey("actors.id"), primary_key=True),
)

quality_board = Table(
    "quality_board",
    Base.metadata,
    Column("governance_id", String(36), ForeignKey("governance_departments.id"), primary_key=True),
    Column("actor_id", String(36), ForeignKey("actors.id"), primary_key=True),
)
