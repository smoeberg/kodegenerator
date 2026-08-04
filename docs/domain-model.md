# DOR Domain Model
*Canonical Domain Primitives for Digital Organization Runtime v0.1*

---

## 📚 Overview

This document defines the **canonical domain model** for DOR (Digital Organization Runtime). These primitives form the foundation of the system and must be implemented consistently across all layers (domain, application, infrastructure).

**Key Principles:**
1. **First-class Domain Objects**: Each primitive is a proper domain object with clear responsibilities
2. **Immutability**: Domain objects should be immutable where possible (state changes via events)
3. **Traceability**: All objects support provenance, audit trails, and causality chains
4. **Governance Integration**: Authorization and policy enforcement are built into the model from the start

---

## 🏗️ Domain Primitives Hierarchy

```
DOR Domain Model
├── Identity & Organization
│   ├── Principal          # Authenticated identity (JWT subject)
│   ├── Organization       # Juridical/operational identity
│   ├── Department         # Organizational unit
│   └── Team               # Sub-unit of a department
│
├── Actors & Roles
│   ├── Actor              # Entity that can perform actions (AI, human, service)
│   ├── RoleDefinition     # Position with capabilities, authority, constraints
│   └── Capability         # Skill that an Actor can have
│
├── Execution
│   ├── Intent             # Goal/desired outcome (triggers Workflow)
│   ├── Workflow           # Process definition (state machine)
│   │   ├── State          # Workflow state
│   │   ├── Transition     # State transition
│   │   └── Gate           # Approval condition
│   └── Task               # Unit of work (atomic execution)
│
├── Outputs
│   └── Artifact           # Verifiable output with versioning & provenance
│       ├── Signature      # Approval/rejection
│       └── Provenance     # Origin history
│
├── Governance
│   ├── Policy             # Rule that constrains execution
│   ├── AuthorizationDecision  # Authorization outcome
│   ├── GovernanceDepartment  # Central governance authority
│   └── GovernanceBoard   # Specific board (Architecture, Security, etc.)
│
└── Events
    ├── Event              # Base event
    ├── DomainEvent        # Domain event (Event Sourcing)
    └── [Specific Events] # IntentCreated, WorkflowStateChanged, etc.
```

---

## 📋 Domain Primitives Reference

---

### 🏢 Identity & Organization

#### Principal
**Purpose:** Represents an authenticated identity (typically from JWT).

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID or external ID) | ✅ |
| `type` | `str` | Type of principal (`"user"`, `"service"`, `"api_key"`) | ✅ |
| `name` | `Optional[str]` | Human-readable name | ❌ |
| `email` | `Optional[str]` | Email address | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `from_jwt(jwt_payload: Dict[str, Any]) -> Principal`: Create from JWT payload

**Relationships:**
- Resolves to an `Actor` via `ActorService`

**File:** `domain/principal.py`

---

#### Organization
**Purpose:** Represents a juridical/operational identity (e.g., company, department).

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `domain` | `Optional[str]` | Domain/industry (e.g., "software-engineering") | ❌ |
| `mission` | `Optional[str]` | Organization mission | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Relationships:**
- Has many `Department`s
- Has many `Actor`s
- Has many `Policy`s
- Has one `GovernanceDepartment`

**Methods:**
- `add_department(department: Department)`
- `add_actor(actor: Actor)`
- `add_policy(policy: Policy)`

**File:** `domain/organization.py`

---

#### Department
**Purpose:** Organizational unit under an Organization.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `manager` | `Optional[Actor]` | Department manager | ❌ |
| `budget` | `float` | Annual budget | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Relationships:**
- Belongs to one `Organization`
- Has many `Team`s
- Has many `Actor`s
- Has many `Policy`s

**Methods:**
- `add_team(team: Team)`
- `add_actor(actor: Actor)`
- `add_policy(policy: Policy)`

**File:** `domain/department.py`

---

#### Team
**Purpose:** Sub-unit of a Department.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `lead` | `Optional[Actor]` | Team lead | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Relationships:**
- Belongs to one `Department`
- Has many `Actor` members
- Has a `backlog` of task IDs

**Methods:**
- `add_member(actor: Actor)`
- `add_task(task_id: str)`

**File:** `domain/team.py`

---

### 👥 Actors & Roles

#### Actor
**Purpose:** Represents an entity that can perform actions in DOR (AI, human, service).

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `type` | `ActorType` | Type of actor (`HUMAN`, `DIGITAL_EMPLOYEE`, `SERVICE`, `EXTERNAL`) | ✅ |
| `identity` | `str` | Human-readable identity (e.g., "GPT-5", "John Doe") | ✅ |
| `status` | `str` | Status (`"active"`, `"inactive"`, `"suspended"`) | ✅ |
| `organization` | `Optional[Organization]` | Organization this Actor belongs to | ❌ |
| `department` | `Optional[Department]` | Department this Actor belongs to | ❌ |
| `team` | `Optional[Team]` | Team this Actor belongs to | ❌ |
| `role` | `Optional[RoleDefinition]` | Role of this Actor | ❌ |
| `capabilities` | `List[Capability]` | List of Capabilities this Actor has | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `add_capability(capability: Capability)`
- `has_capability(capability_id: str) -> bool`
- `can_perform(action: str) -> bool`
- `needs_approval_for(action: str) -> List[str]`

**File:** `domain/actor.py`

---

#### RoleDefinition
**Purpose:** Defines a position with capabilities, authority, and constraints.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name (e.g., "Senior AI Engineer") | ✅ |
| `description` | `str` | Description | ❌ |
| `department_id` | `Optional[str]` | Department this Role belongs to | ❌ |
| `team_id` | `Optional[str]` | Team this Role belongs to | ❌ |
| `capabilities` | `List[str]` | List of Capability IDs required for this Role | ❌ |
| `authority` | `Dict[str, bool]` | What this Role can do (e.g., `{"can_approve": True}`) | ❌ |
| `needs_approval_from` | `Dict[str, List[str]]` | What requires approval (e.g., `{"merge_to_main": ["architecture_reviewer"]}`) | ❌ |
| `responsibilities` | `List[str]` | List of responsibilities | ❌ |
| `organization` | `Optional[Organization]` | Organization this Role belongs to | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `add_capability(capability_id: str)`
- `can_perform(action: str) -> bool`
- `get_required_approvals(action: str) -> List[str]`

**File:** `domain/role.py`

---

#### Capability
**Purpose:** Represents a skill that an Actor can have.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (e.g., "python.fastapi.expert") | ✅ |
| `name` | `str` | Human-readable name (e.g., "FastAPI Expert") | ✅ |
| `description` | `str` | Description | ❌ |
| `level` | `CapabilityLevel` | Proficiency level (`BEGINNER`, `INTERMEDIATE`, `ADVANCED`, `EXPERT`) | ✅ |
| `certification` | `Optional[str]` | Certification (e.g., "Verified by EIRA") | ❌ |
| `category` | `str` | Category (e.g., "engineering", "security", "management") | ❌ |
| `organization` | `Optional[Organization]` | Organization this Capability belongs to | ❌ |
| `used_by` | `List[str]` | List of Actor IDs that have this Capability | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `add_user(actor_id: str)`

**File:** `domain/capability.py`

---

### ⚙️ Execution

#### Intent
**Purpose:** Represents a goal or desired outcome that triggers a Workflow.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `goal` | `str` | Primary objective (e.g., "Implement OAuth2 Authentication") | ✅ |
| `description` | `str` | Detailed description | ❌ |
| `priority` | `IntentPriority` | Priority level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) | ✅ |
| `constraints` | `Dict[str, Any]` | Additional constraints (e.g., `{"security_level": "high"}`) | ❌ |
| `required_capabilities` | `List[str]` | List of Capability IDs required | ❌ |
| `status` | `IntentStatus` | Current status (`CREATED`, `PROCESSING`, `RESOLVED`, `FAILED`, `CANCELLED`) | ✅ |
| `creator` | `Optional[Actor]` | Actor who created this Intent | ❌ |
| `organization` | `Optional[Organization]` | Organization this Intent belongs to | ❌ |
| `workflow` | `Optional[Workflow]` | Workflow this Intent resolved to | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `matches_actor(actor: Actor) -> bool`: Check if Actor can handle this Intent
- `resolve_workflow(workflows: List[Workflow]) -> Optional[Workflow]`: Find matching Workflow
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Intent`

**File:** `domain/intent.py`

---

#### Workflow
**Purpose:** Represents a process definition with states, transitions, and gates.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `states` | `List[State]` | List of states in this Workflow | ❌ |
| `transitions` | `List[Transition]` | List of valid transitions | ❌ |
| `gates` | `List[Gate]` | List of approval gates | ❌ |
| `current_state` | `Optional[State]` | Current state of this Workflow instance | ❌ |
| `status` | `WorkflowStatus` | Runtime status (`PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`) | ✅ |
| `version` | `str` | Version of this Workflow definition | ✅ |
| `organization` | `Optional[Organization]` | Organization this Workflow belongs to | ❌ |
| `intent` | `Optional[Intent]` | Intent that triggered this Workflow | ❌ |
| `tasks` | `List[Task]` | List of Tasks in this Workflow | ❌ |
| `artifacts` | `List[Artifact]` | List of Artifacts produced | ❌ |
| `events` | `List[Event]` | List of Events related to this Workflow | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `add_state(state: State)`
- `add_transition(transition: Transition)`
- `add_gate(gate: Gate)`
- `get_transition(from_state: WorkflowState, to_state: WorkflowState) -> Optional[Transition]`
- `get_gate(gate_id: str) -> Optional[Gate]`
- `can_transition(new_state: WorkflowState, actor: Actor, artifact: Optional[Artifact]) -> bool`
- `transition_to(new_state: WorkflowState, actor: Actor, artifact: Optional[Artifact], evidence: Optional[Dict]) -> List[Event]`
- `apply_event(event: Event)`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Workflow`

**File:** `domain/workflow.py`

---

#### State
**Purpose:** Represents a state in a Workflow's state machine.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier | ✅ |
| `name` | `WorkflowState` | The state enum value | ✅ |
| `description` | `str` | Human-readable description | ❌ |
| `is_initial` | `bool` | Whether this is the starting state | ❌ |
| `is_final` | `bool` | Whether this is a terminal state | ❌ |

**File:** `domain/workflow.py`

---

#### Transition
**Purpose:** Represents a transition between states in a Workflow.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `from_state` | `WorkflowState` | Source state | ✅ |
| `to_state` | `WorkflowState` | Target state | ✅ |
| `condition` | `Optional[str]` | Condition expression (evaluated by ConditionEvaluator) | ❌ |
| `gate_id` | `Optional[str]` | Gate ID that must be satisfied | ❌ |
| `description` | `str` | Human-readable description | ❌ |

**File:** `domain/workflow.py`

---

#### Gate
**Purpose:** Represents a gate (condition) that must be satisfied to proceed in a Workflow.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `required_approvals` | `List[str]` | List of role IDs that must approve | ❌ |
| `min_consensus_score` | `float` | Minimum consensus score (0-100) | ❌ |
| `conditions` | `Dict[str, Any]` | Additional conditions (e.g., `{"test_coverage": 0.95}`) | ❌ |

**Methods:**
- `is_satisfied(artifact: Optional[Artifact], approvals: List[str]) -> bool`

**File:** `domain/workflow.py`

---

#### Task
**Purpose:** Represents a unit of work to be executed within a Workflow.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description of the work | ❌ |
| `status` | `TaskStatus` | Current status (`PENDING`, `READY`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `BLOCKED`, `CANCELLED`, `RETRYING`) | ✅ |
| `dependency_status` | `DependencyStatus` | Status of dependencies (`WAITING_FOR_DEPENDENCY`, `READY`) | ✅ |
| `priority` | `TaskPriority` | Priority level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) | ✅ |
| `workflow_id` | `Optional[str]` | Workflow this Task belongs to | ❌ |
| `organization_id` | `Optional[str]` | Organization this Task belongs to | ❌ |
| `dependencies` | `List[str]` | List of Task IDs that must complete first | ❌ |
| `assigned_actor` | `Optional[Actor]` | Actor this Task is assigned to | ❌ |
| `input_artifacts` | `List[str]` | List of Artifact IDs used as input | ❌ |
| `output_artifacts` | `List[str]` | List of Artifact IDs produced as output | ❌ |
| `retry_count` | `int` | Number of retry attempts | ❌ |
| `max_retries` | `int` | Maximum number of retries | ❌ |
| `last_error` | `Optional[str]` | Error message from last failure | ❌ |
| `execution_parameters` | `Dict[str, Any]` | Parameters for execution | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `can_start(completed_tasks: List[str]) -> bool`
- `is_blocked(completed_tasks: List[str]) -> bool`
- `update_dependency_status(completed_tasks: List[str])`
- `assign_to(actor: Actor)`
- `start()`
- `succeed(output_artifacts: List[str], execution_result: Optional[Dict])`
- `fail(error: str, retry: bool = False)`
- `cancel()`
- `block(reason: str)`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Task`

**File:** `domain/task.py`

---

### 📦 Outputs

#### Artifact
**Purpose:** Represents a verifiable organizational output with versioning, provenance, and governance.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `artifact_id` | `str` | Human-readable identifier (e.g., "ADR-001") | ✅ |
| `version` | `str` | Semantic version (e.g., "1.0.0") | ✅ |
| `artifact_type` | `ArtifactType` | Type of Artifact (`SPECIFICATION`, `IMPLEMENTATION`, `REVIEW`, etc.) | ✅ |
| `content_digest` | `str` | SHA-256 hash of the content | ✅ |
| `content` | `Optional[str]` | The actual content (may be stored externally) | ❌ |
| `content_location` | `Optional[str]` | URI to the content (if stored externally) | ❌ |
| `content_type` | `str` | MIME type or custom type | ✅ |
| `organization_id` | `Optional[str]` | Organization this Artifact belongs to | ❌ |
| `owner` | `Optional[Actor]` | Actor who created this Artifact | ❌ |
| `state` | `ArtifactState` | Current state (`DRAFT`, `SUBMITTED`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `RELEASED`, `ARCHIVED`) | ✅ |
| `governance_state` | `GovernanceState` | Governance state (`DRAFT`, `SUBMITTED`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `EXEMPT`) | ✅ |
| `provenance` | `Provenance` | Provenance information | ✅ |
| `signatures` | `List[Signature]` | List of approval/rejection signatures | ❌ |
| `parents` | `List[str]` | List of parent Artifact IDs | ❌ |
| `children` | `List[str]` | List of child Artifact IDs | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `calculate_hash(content: str) -> str`: Calculate SHA-256 hash
- `verify_content(content: str) -> bool`: Verify content matches digest
- `add_signature(signature: Signature)`
- `is_approved() -> bool`: Check if all signatures are "approved"
- `get_consensus_score() -> float`: Calculate consensus score (0-100)
- `add_parent(parent_id: str)`
- `add_child(child_id: str)`
- `submit_for_review()`
- `approve(role_id: str, actor_id: str, comments: str = "")`
- `reject(role_id: str, actor_id: str, comments: str = "")`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Artifact`

**File:** `domain/artifact.py`

---

#### Signature
**Purpose:** Represents an approval or rejection on an Artifact.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `role_id` | `str` | Role ID of the signer (e.g., "architecture_reviewer") | ✅ |
| `actor_id` | `str` | Actor ID of the signer | ✅ |
| `status` | `str` | Status (`"approved"`, `"rejected"`, `"needs_changes"`) | ✅ |
| `comments` | `str` | Comments from the signer | ❌ |
| `timestamp` | `datetime` | When the signature was created | ✅ |
| `evidence` | `Optional[Dict[str, Any]]` | Evidence supporting the signature | ❌ |

**Methods:**
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Signature`

**File:** `domain/artifact.py`

---

#### Provenance
**Purpose:** Represents the origin history of an Artifact.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `intent_id` | `Optional[str]` | Intent that triggered creation | ❌ |
| `workflow_id` | `Optional[str]` | Workflow that produced this Artifact | ❌ |
| `task_id` | `Optional[str]` | Task that directly produced this Artifact | ❌ |
| `execution_id` | `Optional[str]` | Execution ID (if applicable) | ❌ |
| `model_id` | `Optional[str]` | AI model used (if applicable) | ❌ |
| `model_version` | `Optional[str]` | Version of the AI model | ❌ |
| `prompt` | `Optional[str]` | Original prompt (for reproducibility) | ❌ |
| `input_artifacts` | `List[str]` | List of Artifact IDs used as input | ❌ |
| `parent_artifacts` | `List[str]` | List of parent Artifact IDs | ❌ |

**Methods:**
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Provenance`

**File:** `domain/artifact.py`

---

### ⚖️ Governance

#### Policy
**Purpose:** Represents a governance rule that constrains and controls execution in DOR.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `scope` | `PolicyScope` | Scope of the Policy (`GLOBAL`, `DEPARTMENT`, `TEAM`, `WORKFLOW`, `TASK`, `ARTIFACT`, `ORGANIZATION`) | ✅ |
| `scope_id` | `Optional[str]` | ID of the scope target (e.g., department_id) | ❌ |
| `enforcement_point` | `EnforcementPoint` | When the Policy is enforced (`PRE_EXECUTION`, `POST_EXECUTION`, `ON_EVENT`, `SCHEDULED`) | ✅ |
| `conditions` | `Dict[str, Any]` | Conditions that must be satisfied | ❌ |
| `actions` | `Dict[str, Any]` | Actions to take if violated | ❌ |
| `organization` | `Optional[Organization]` | Organization this Policy belongs to | ❌ |
| `enabled` | `bool` | Whether this Policy is enabled | ✅ |
| `priority` | `int` | Priority for enforcement (higher = first) | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `applies_to(target_type: str, target_id: Optional[str]) -> bool`: Check if Policy applies to target
- `get_action(violation_type: str) -> PolicyAction`: Get action for violation type
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Policy`

**File:** `domain/policy.py`

---

#### PolicyViolation
**Purpose:** Represents a violation of a Policy.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `policy_id` | `str` | ID of the violated Policy | ✅ |
| `policy_name` | `str` | Name of the violated Policy | ✅ |
| `violation_type` | `str` | Type of violation | ✅ |
| `message` | `str` | Human-readable message | ✅ |
| `details` | `Dict[str, Any]` | Additional details | ❌ |
| `timestamp` | `datetime` | When the violation occurred | ✅ |
| `actor_id` | `Optional[str]` | Actor responsible for the violation | ❌ |
| `resource_type` | `Optional[str]` | Type of resource involved | ❌ |
| `resource_id` | `Optional[str]` | ID of the resource involved | ❌ |

**Methods:**
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> PolicyViolation`

**File:** `domain/policy.py`

---

#### AuthorizationDecision
**Purpose:** Represents a decision about whether an action is authorized.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `decision_id` | `str` | Unique identifier (UUID) | ✅ |
| `subject` | `Optional[Principal]` | The authenticated Principal | ❌ |
| `actor_id` | `Optional[str]` | The Actor ID (DOR identity) | ❌ |
| `organization_id` | `Optional[str]` | Organization ID | ❌ |
| `action` | `str` | The action being attempted | ✅ |
| `resource_type` | `str` | Type of resource | ✅ |
| `resource_id` | `Optional[str]` | ID of the resource | ❌ |
| `policy_ids` | `List[str]` | List of Policy IDs that were evaluated | ❌ |
| `violations` | `List[PolicyViolation]` | List of PolicyViolations | ❌ |
| `decision` | `bool` | Whether the action is allowed (True = ALLOW, False = DENY) | ✅ |
| `reason` | `str` | Human-readable reason | ❌ |
| `evidence` | `Dict[str, Any]` | Additional evidence | ❌ |
| `issued_at` | `datetime` | When the decision was made | ✅ |
| `expires_at` | `Optional[datetime]` | When the decision expires | ❌ |

**Methods:**
- `is_allowed() -> bool`
- `is_denied() -> bool`
- `has_violations() -> bool`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> AuthorizationDecision`

**File:** `domain/policy.py`

---

#### GovernanceDepartment
**Purpose:** Represents the central governance authority for an Organization.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `organization` | `Optional[Organization]` | Organization this department belongs to | ❌ |
| `boards` | `Dict[BoardType, GovernanceBoard]` | Dictionary of boards by type | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `get_board(board_type: BoardType) -> Optional[GovernanceBoard]`
- `add_board(board: GovernanceBoard)`
- `remove_board(board_type: BoardType)`
- `approve_artifact(artifact: Artifact, board_type: BoardType, actor: Actor, comments: str = "") -> bool`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> GovernanceDepartment`

**File:** `domain/governance.py`

---

#### GovernanceBoard
**Purpose:** Represents a specific governance board (e.g., Architecture Board, Security Board).

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `board_type` | `BoardType` | Type of board (`ARCHITECTURE`, `SECURITY`, `COMPLIANCE`, etc.) | ✅ |
| `name` | `str` | Human-readable name | ✅ |
| `description` | `str` | Description | ❌ |
| `organization` | `Optional[Organization]` | Organization this board belongs to | ❌ |
| `members` | `List[Actor]` | List of Actors who are members | ❌ |
| `policies` | `List[Policy]` | List of Policies this board enforces | ❌ |
| `decisions` | `List[GovernanceDecision]` | List of decisions made by this board | ❌ |
| `quorum` | `int` | Minimum number of members required for a decision | ❌ |
| `created_at` | `datetime` | Creation timestamp | ✅ |
| `updated_at` | `datetime` | Last update timestamp | ✅ |

**Methods:**
- `add_member(actor: Actor)`
- `remove_member(actor: Actor)`
- `has_quorum() -> bool`
- `can_decide(actor: Actor) -> bool`
- `make_decision(artifact: Artifact, decision: DecisionStatus, actor: Actor, comments: str = "", evidence: Optional[Dict] = None) -> GovernanceDecision`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> GovernanceBoard`

**File:** `domain/governance.py`

---

#### GovernanceDecision
**Purpose:** Represents a decision made by a Governance Board.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `board_type` | `BoardType` | Type of board that made the decision | ✅ |
| `artifact_id` | `Optional[str]` | Artifact this decision pertains to | ❌ |
| `decision` | `DecisionStatus` | Decision status (`PENDING`, `APPROVED`, `REJECTED`, `DEFERRED`, `EXEMPT`) | ✅ |
| `comments` | `str` | Comments from the board | ❌ |
| `evidence` | `Dict[str, Any]` | Evidence supporting the decision | ❌ |
| `voting_record` | `Dict[str, str]` | Record of how each board member voted | ❌ |
| `timestamp` | `datetime` | When the decision was made | ✅ |
| `actor_id` | `Optional[str]` | Actor who recorded the decision | ❌ |

**Methods:**
- `is_approved() -> bool`
- `is_rejected() -> bool`
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> GovernanceDecision`

**File:** `domain/governance.py`

---

### 📜 Events

#### Event
**Purpose:** Base class for all Events in DOR.

**Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | `str` | Unique identifier (UUID) | ✅ |
| `event_type` | `EventType` | Type of Event | ✅ |
| `aggregate_id` | `Optional[str]` | ID of the aggregate this Event pertains to | ❌ |
| `aggregate_type` | `Optional[str]` | Type of aggregate (e.g., "workflow", "task") | ❌ |
| `organization_id` | `Optional[str]` | Organization this Event belongs to | ❌ |
| `actor_id` | `Optional[str]` | Actor who triggered this Event | ❌ |
| `timestamp` | `datetime` | When the Event occurred | ✅ |
| `correlation_id` | `Optional[str]` | ID to correlate related Events | ❌ |
| `causation_id` | `Optional[str]` | ID of the Event that caused this Event | ❌ |
| `metadata` | `Dict[str, Any]` | Additional context | ❌ |

**Methods:**
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> Event`

**File:** `domain/event.py`

---

#### DomainEvent
**Purpose:** Base class for Domain Events (Event Sourcing).

**Inherits:** `Event`

**Additional Attributes:**
| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `schema_version` | `str` | Version of the Event schema | ✅ |
| `sequence` | `int` | Sequence number within the aggregate | ✅ |

**Methods:**
- `to_dict() -> Dict[str, Any]`
- `from_dict(data: Dict[str, Any]) -> DomainEvent`

**File:** `domain/event.py`

---

#### Specific Event Types

All specific event types inherit from `DomainEvent` and represent state changes in domain objects:

- **Intent Events:**
  - `IntentCreatedEvent`: Intent was created
  - `IntentResolvedEvent`: Intent was resolved to a Workflow

- **Workflow Events:**
  - `WorkflowStateChangedEvent`: Workflow changed state

- **Task Events:**
  - `TaskCreatedEvent`: Task was created
  - `TaskAssignedEvent`: Task was assigned to an Actor
  - `TaskCompletedEvent`: Task was completed

- **Artifact Events:**
  - `ArtifactCreatedEvent`: Artifact was created
  - `ArtifactSubmittedEvent`: Artifact was submitted for review
  - `ArtifactApprovedEvent`: Artifact was approved

- **Governance Events:**
  - `PolicyViolatedEvent`: Policy was violated
  - `GovernanceApprovalEvent`: Governance approval occurred

- **Authorization Events:**
  - `AuthorizationDeniedEvent`: Authorization was denied

- **Execution Events:**
  - `ExecutionCompletedEvent`: Execution was completed

**Factory Functions:**
- `create_workflow_state_changed_event(...)`
- `create_task_completed_event(...)`
- `create_artifact_created_event(...)`
- `create_policy_violated_event(...)`
- `create_authorization_denied_event(...)`

**File:** `domain/event.py`

---

## 🔗 Relationships Between Primitives

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            ORGANIZATION                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────────┐  │
│  │  Department  │  │    Team     │  │        GovernanceDepartment       │  │
│  │             │  │             │  │  ┌─────────────┐  ┌─────────────┐ │  │
│  │  ┌───────┐  │  │  ┌───────┐  │  │  │ Architecture │  │  Security   │ │  │
│  │  │ Actor │  │  │  │ Actor │  │  │  │   Board    │  │    Board    │ │  │
│  │  └───────┘  │  │  └───────┘  │  │  └─────────────┘  └─────────────┘ │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          IDENTITY & AUTHORIZATION                         │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────────────────┐  │
│  │  Principal   │─────▶│    Actor    │─────▶│   AuthorizationDecision   │  │
│  └─────────────┘      └─────────────┘      └─────────────────────────┘  │
│         │                     │                              │          │
│         │                     ▼                              ▼          │
│         │              ┌─────────────┐                ┌─────────────┐      │
│         │              │   Role      │                │   Policy     │      │
│         │              └─────────────┘                └─────────────┘      │
│         │                     │                              │          │
│         └─────────────────────┴──────────────────────────┴──────────────┘
│                                                                       │
│                        ┌──────────────────────────────────────────┐   │
│                        │           EXECUTION CHAIN                  │   │
│                        │  ┌─────────┐  ┌─────────┐  ┌─────────┐   │   │
│                        │  │  Intent  │─▶│ Workflow│─▶│  Task   │   │   │
│                        │  └─────────┘  └─────────┘  └─────────┘   │   │
│                        │       │           │            │          │   │
│                        │       ▼           ▼            ▼          │   │
│                        │  ┌─────────────────────────────────────┐ │   │
│                        │  │           Artifact (Output)            │ │   │
│                        │  │  ┌─────────┐  ┌─────────────────────┐  │ │   │
│                        │  │  │Provenance│  │    Signatures        │  │ │   │
│                        │  │  └─────────┘  └─────────────────────┘  │ │   │
│                        │  └─────────────────────────────────────┘ │   │
│                        │                                          │   │
│                        │              ┌───────────────────────┐    │   │
│                        │              │    Domain Events       │    │   │
│                        │              │  (Event Sourcing)      │    │   │
│                        │              └───────────────────────┘    │   │
│                        └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📜 End-to-End Flow

The following sequence represents the **Definition of Done** for DOR Foundation v0.1:

```
1. Authenticated Principal (JWT)
   ↓
2. OrganizationContext (Request-scoped)
   ↓
3. Intent (Goal + Constraints)
   ↓
4. AuthorizationDecision (Policy Check)
   ↓
5. Workflow (State Machine)
   ↓
6. Task (Unit of Work)
   ↓
7. Execution (AI/Service with Verified Side Effects)
   ↓
8. Artifact (Versioned Output with Provenance)
   ↓
9. DomainEvent (Durable, Ordered, Traceable)
   ↓
10. Audit Trail (Queryable, Tamper-Evident)
```

---

## 🔒 Security & Governance Integration

### Authorization Flow
```
Request
  ↓
JWT Validation → Principal
  ↓
Actor Resolution (Principal → Actor)
  ↓
OrganizationContext (Org Isolation)
  ↓
Policy Enforcement Point (PEP)
  ↓
  ├─ Check Capabilities
  ├─ Check Policies
  ├─ Check Governance State
  └─ Return AuthorizationDecision
  ↓
If ALLOWED: Proceed with Action
If DENIED: Return 403 Forbidden + Log Event
```

### Governance Flow
```
Artifact Created
  ↓
Submit for Review
  ↓
Policy Check (e.g., "requires_architecture_approval")
  ↓
If Required: Route to Governance Board
  ↓
Board Members Review
  ↓
Signatures Collected
  ↓
Consensus Check (e.g., min_consensus_score > 80)
  ↓
If Approved: Artifact.state = APPROVED
If Rejected: Artifact.state = REJECTED
  ↓
Emit GovernanceApprovalEvent / GovernanceRejectionEvent
```

---

## 📁 File Structure

```
domain/
├── __init__.py           # Re-exports all primitives
├── organization.py      # Organization, Department, Team
├── principal.py         # Principal (authenticated identity)
├── actor.py             # Actor, ActorType
├── role.py              # RoleDefinition
├── capability.py        # Capability, CapabilityLevel
├── intent.py            # Intent, IntentPriority, IntentStatus
├── workflow.py          # Workflow, WorkflowState, WorkflowStatus, State, Transition, Gate
├── task.py              # Task, TaskStatus, TaskPriority, DependencyStatus
├── artifact.py          # Artifact, ArtifactType, ArtifactState, GovernanceState, Signature, Provenance
├── policy.py            # Policy, PolicyScope, EnforcementPoint, PolicyAction, PolicyViolation, AuthorizationDecision
├── governance.py        # GovernanceDepartment, GovernanceBoard, GovernanceDecision, BoardType, DecisionStatus
└── event.py             # Event, EventType, DomainEvent, [Specific Events], Factory Functions
```

---

## ✅ Definition of Done (v0.1)

For DOR Foundation v0.1 to be considered complete, the following must be true:

1. ✅ **All domain primitives are defined** in `domain/` with clear contracts
2. ✅ **No duplicate models** (SQLAlchemy models moved to `infrastructure/`)  
3. ✅ **All primitives can be serialized/deserialized** via `to_dict()`/`from_dict()`
4. ✅ **Relationships are clearly defined** (but not necessarily persisted)
5. ✅ **Governance is integrated** (AuthorizationDecision, Policy, GovernanceBoard)
6. ✅ **Event Sourcing pattern is established** (DomainEvent, sequence, schema_version)
7. ✅ **Provenance tracking is supported** (Artifact.Provenance)
8. ✅ **Documentation is complete** (this document)

---

## 🚀 Next Steps

After completing the Canonical Domain Model (Fase 0), proceed to:

1. **Fase 1: Persistence** - Implement database layer with SQLAlchemy
2. **Fase 2: Identity & OrganizationContext** - Implement authentication and org isolation
3. **Fase 3: Authorization & Policy** - Implement governance from the start
4. **Fase 4: Workflow Aggregate** - Implement state machine with invariants
5. **Fase 5: Event Infrastructure** - Implement Event Store + Outbox Pattern
6. **Fase 6: Execution Contract** - Implement Task execution with verified side effects
7. **Fase 7: Artifact & Provenance** - Implement first-class Artifact primitive
8. **Fase 8: Integration Tests** - Validate end-to-end flow

---

*Document Version: 1.0*
*Last Updated: 4 August 2026*
*Owner: DOR Architecture Team*
