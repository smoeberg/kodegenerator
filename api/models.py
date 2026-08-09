# api/models.py
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ActorTypeEnum(str, Enum):
    HUMAN = "human"
    DIGITAL_EMPLOYEE = "digital_employee"
    SERVICE = "service"
    EXTERNAL = "external"


class WorkflowStateEnum(str, Enum):
    NEW = "new"
    ANALYSIS = "analysis"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    APPROVED = "approved"
    RELEASED = "released"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ArtifactStateEnum(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RELEASED = "released"
    ARCHIVED = "archived"


class ArtifactTypeEnum(str, Enum):
    SPECIFICATION = "specification"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    DECISION = "decision"
    RELEASE = "release"
    LEGAL = "legal"
    FINANCIAL = "financial"


class TaskStatusEnum(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriorityEnum(int, Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class CapabilityLevelEnum(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class IntentPriorityEnum(int, Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class OrganizationBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationResponse(OrganizationBase):
    created_at: datetime
    updated_at: datetime


class ActorBase(BaseModel):
    id: str
    type: ActorTypeEnum
    identity: str
    status: str = "active"


class ActorCreate(ActorBase):
    role_id: Optional[str] = None
    department_id: Optional[str] = None
    team_id: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)


class ActorResponse(ActorBase):
    role: Optional[Dict[str, Any]] = None
    department: Optional[Dict[str, Any]] = None
    team: Optional[Dict[str, Any]] = None
    capabilities: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RoleDefinitionBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    authority: Dict[str, bool] = Field(default_factory=dict)
    needs_approval_from: Dict[str, List[str]] = Field(default_factory=dict)
    responsibilities: List[str] = Field(default_factory=list)


class RoleDefinitionCreate(RoleDefinitionBase):
    pass


class RoleDefinitionResponse(RoleDefinitionBase):
    created_at: datetime
    updated_at: datetime


class CapabilityBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    level: CapabilityLevelEnum = CapabilityLevelEnum.BEGINNER
    certification: Optional[str] = None


class CapabilityCreate(CapabilityBase):
    pass


class CapabilityResponse(CapabilityBase):
    used_by: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class IntentBase(BaseModel):
    id: str
    goal: str
    description: Optional[str] = None
    priority: IntentPriorityEnum = IntentPriorityEnum.MEDIUM
    constraints: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)


class IntentCreate(IntentBase):
    creator_id: str
    organization_id: str


class IntentResponse(IntentBase):
    creator: Optional[Dict[str, Any]] = None
    workflow: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class WorkflowBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    current_state: Optional[WorkflowStateEnum] = None


class WorkflowCreate(WorkflowBase):
    intent_id: Optional[str] = None
    template_id: Optional[str] = None


class WorkflowTransitionRequest(BaseModel):
    """Authenticated request for the canonical Phase 3 command boundary."""

    organization_id: str
    command_id: str = Field(min_length=1)
    new_state: WorkflowStateEnum


class WorkflowResponse(WorkflowBase):
    states: List[Dict[str, Any]] = Field(default_factory=list)
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    gates: List[Dict[str, Any]] = Field(default_factory=list)
    intent: Optional[Dict[str, Any]] = None
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaskBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: TaskStatusEnum = TaskStatusEnum.PENDING
    priority: TaskPriorityEnum = TaskPriorityEnum.MEDIUM
    workflow_id: Optional[str] = None
    assigned_actor_id: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    input_artifacts: List[str] = Field(default_factory=list)
    output_artifacts: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskCreate(TaskBase):
    pass


class TaskResponse(TaskBase):
    workflow: Optional[Dict[str, Any]] = None
    assigned_actor: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class ArtifactBase(BaseModel):
    id: str
    version: str
    artifact_type: ArtifactTypeEnum
    hash: str = ""
    state: ArtifactStateEnum = ArtifactStateEnum.DRAFT
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactCreate(ArtifactBase):
    owner_id: str
    department_id: Optional[str] = None
    workflow_id: Optional[str] = None


class ArtifactResponse(ArtifactBase):
    owner: Optional[Dict[str, Any]] = None
    department: Optional[Dict[str, Any]] = None
    workflow: Optional[Dict[str, Any]] = None
    signatures: List[Dict[str, Any]] = Field(default_factory=list)
    parents: List[str] = Field(default_factory=list)
    children: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkflowTemplateBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    required_capabilities: List[str] = Field(default_factory=list)
    default_priority: TaskPriorityEnum = TaskPriorityEnum.MEDIUM


class WorkflowTemplateResponse(WorkflowTemplateBase):
    states: List[Dict[str, Any]] = Field(default_factory=list)
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    gates: List[Dict[str, Any]] = Field(default_factory=list)
    default_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: bool = False


class UserInDB(User):
    hashed_password: str


class ImplementationContextItemInput(BaseModel):
    """One explicitly supplied item for a bounded Context Packet."""

    source: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: Any
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: str = ""
    sensitivity: Literal["public", "normal", "sensitive"] = "normal"


class ImplementationProposalRequest(BaseModel):
    """Authenticated command for one governed patch proposal."""

    organization_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    allowed_paths: List[str] = Field(min_length=1)
    max_files: int = Field(default=1, ge=1)
    max_changed_lines: int = Field(default=100, ge=1)
    context_items: List[ImplementationContextItemInput] = Field(min_length=1)


class ImplementationProposalArtifactResponse(BaseModel):
    proposal_id: str
    provider_id: str
    diff_sha256: str
    touched_paths: List[str]
    changed_lines: int
    unified_diff: str


class ImplementationProposalResponse(BaseModel):
    command_id: str
    agent_identity: str
    context_packet_id: str
    request_fingerprint: str
    authority_decision: str
    authority_policy_id: str
    authority_policy_version: str
    execution_id: str
    execution_status: str
    outcome_id: str
    outcome_status: str
    provenance_id: str
    replayed: bool
    proposal: ImplementationProposalArtifactResponse


class ImplementationPatchExecutionRequest(BaseModel):
    """Authenticated command for one stored proposal; argv is never caller input."""

    organization_id: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    proposal_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class ImplementationPatchFileResponse(BaseModel):
    path: str
    exists: bool
    sha256: Optional[str]
    byte_count: int
    mode: Optional[int]


class ImplementationToolLogResponse(BaseModel):
    artifact_id: str
    sha256: str
    byte_count: int
    content: str
    truncated: bool


class ImplementationToolEvidenceResponse(BaseModel):
    evidence_id: str
    tool_id: str
    kind: str
    tool_fingerprint: str
    artifact_id: str
    status: str
    passed: bool
    exit_code: Optional[int]
    stdout: ImplementationToolLogResponse
    stderr: ImplementationToolLogResponse


class ImplementationPatchArtifactResponse(BaseModel):
    artifact_id: str
    proposal_id: str
    diff_sha256: str
    baseline_fingerprint: str
    files: List[ImplementationPatchFileResponse]


class ImplementationPatchExecutionResponse(BaseModel):
    command_id: str
    agent_identity: str
    request_fingerprint: str
    proposal_id: str
    baseline_fingerprint: str
    toolchain_fingerprint: str
    authority_decision: str
    authority_policy_id: str
    authority_policy_version: str
    execution_id: str
    execution_status: str
    outcome_id: str
    outcome_status: str
    provenance_id: str
    replayed: bool
    record_id: str
    record_status: str
    committed: bool
    rolled_back: bool
    error: Optional[str]
    artifact: Optional[ImplementationPatchArtifactResponse]
    evidence: List[ImplementationToolEvidenceResponse]
