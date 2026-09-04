# GUI Live API Parameter Kortlægning

## Dokumentation af alle konfigurerbare og monitorerbare parametre i DOR systemet

---

## 📋 Oversigt

Dette dokument kortlægger **alle** parametre, indstillinger, data og kontrolpunkter i DOR systemet der kan:
- **Ændres** via GUI (Streamlit Dashboard)
- **Monitoreres** i realtid
- **Styres** via FastAPI backend (`http://api:8000`)

---

## 🎯 System Arkitektur

### Dashboard Sektioner (7+ Sektioner)

| Sektion | Beskrivelse | Data Kilde | API Endpoints | Konfigurerbar | Monitorerbar |
|---------|-------------|------------|---------------|---------------|--------------|
| **1. Multi-bot Control Plane** | Konfiguration af bots, connections, deployments, profiler, roller | Control Plane API | `/api/v1/bot-governance/*` | ✅ Ja | ✅ Ja |
| **2. System Generator & Workflow** | End-to-end wizard for systemgenerering | Workflow API | `/workflows`, `/pipeline` | ✅ Ja | ✅ Ja |
| **3. Swarm Fleet Monitor** | Real-time monitoring af 20+ samtidige bots | Swarm API | `/api/v1/swarm/*`, `/api/v1/swarm/ops/*` | ❌ Nej | ✅ Ja |
| **4. Decision Cockpit (HITL)** | Human-in-the-loop beslutninger | Decisions API | `/api/v1/decisions` | ✅ Ja | ✅ Ja |
| **5. Indstillinger & Integrationer** | Systemkonfiguration (Redmine, etc.) | Runtime Config | N/A | ✅ Ja | ❌ Nej |
| **6. Overblik & Systemtilstand** | System metrics og status | Operations Metrics | `/api/v1/swarm/ops/*` | ❌ Nej | ✅ Ja |
| **7. Digitale Medarbejdere** | Agent oversigt og styring | Agents API | `/api/v1/agents*` | ✅ Ja | ✅ Ja |
| **8. Opret Ny Agent** | Agent oprettelseswizard | Agents API | `/api/v1/agents` | ✅ Ja | ❌ Nej |
| **9. Afdelinger & Teams** | Organisationsstruktur | Organizations API | `/api/v1/organizations*` | ✅ Ja | ✅ Ja |
| **10. Opgaver (Tasks)** | Task oversigt og styring | Tasks API | `/api/v1/tasks*` | ✅ Ja | ✅ Ja |
| **11. Audit Log & Hændelser** | System logs og audit trail | Event Log API | `/api/v1/events*` | ❌ Nej | ✅ Ja |

---

## 🔧 Konfigurerbare Parametre

### 1. System Configuration (Indstillinger & Integrationer)

#### 1.1 Redmine Integration
```python
# Miljøvariable
REDMINE_URL: str = "https://redmine.example.com"
REDMINE_API_KEY: str = "***"
REDMINE_PROJECT_ID: str = "dor"
REDMINE_TRACKER_ID: str = "1"
REDMINE_SEVERITY: str = "ERROR"  # [CRITICAL, ERROR, WARNING, INFO, DEBUG]
```

**GUI Kontrol:**
- ✅ Kan ændres via Dashboard → Indstillinger & Integrationer → Redmine Issue Tracker
- ✅ Test forbindelse funktion
- ✅ Gem permanent i .env fil

#### 1.2 Database Configuration
```python
# Miljøvariable
DOR_DB_PATH: str = "dor_runtime.db"  # Default for SQLite
DATABASE_URL: str = "postgresql+psycopg://user:pass@postgres:5432/dor_runtime"
DOR_IDENTITY_DATABASE_URL: str = "..."
DOR_PIPELINE_DATABASE_URL: str = "..."
```

**GUI Kontrol:**
- ❌ Kan kun vises (read-only) i dashboard
- ✅ Kan ændres via miljøvariable

#### 1.3 API Configuration
```python
DOR_API_URL: str = "http://localhost:8000"
DOR_API_TOKEN: str = "***"  # Bearer token for authentication
DOR_ORG_ID: str = "dor-org"  # Organisation ID
```

**GUI Kontrol:**
- ✅ Kan konfigureres i Multi-bot Control Plane
- ✅ Kan gemmes i session state

#### 1.4 JWT & Security Configuration
```python
# Produktion kræver:
DOR_JWT_SECRET_KEY: str = "***"
DOR_JWT_SIGNING_KEYS: str = "***"
DOR_JWT_ACTIVE_KEY_ID: str = "***"
DOR_ADMIN_PASSWORD: str = "***"  # Dashboard adgang
DOR_ADMIN_ORGANIZATION_ID: str = "***"
DOR_AUTHORITY_SIGNING_KEY: str = "***"
DOR_ENCRYPTION_KEY: str = "***"
```

**GUI Kontrol:**
- ❌ Kan kun konfigureres via miljøvariable
- ⚠️ Kræves for production

#### 1.5 Queue & Storage Configuration
```python
DOR_QUEUE_BACKEND: str = "database"  # eller "memory"
ARTIFACT_STORE_URL: str = "http://minio:9000"
ARTIFACT_BUCKET: str = "dor-artifacts"
AWS_ACCESS_KEY_ID: str = "***"
AWS_SECRET_ACCESS_KEY: str = "***"
AWS_DEFAULT_REGION: str = "eu-central-1"
```

**GUI Kontrol:**
- ❌ Kan kun konfigureres via miljøvariable

#### 1.6 Monitoring & Tracing
```python
OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
DOR_ENV: str = "production"  # eller "development"
```

---

### 2. Multi-bot Control Plane Parametre

#### 2.1 Connections (Forbindelser til AI-providere)

**API Endpoint:** `POST /api/v1/bot-governance/connections`

```python
# Oprettelsesparametre
connection_id: str = "connection-mistral-eu-1"
organization_id: str = "dor-org"
brand: str = "mistral"  # [mistral, openai, anthropic, etc.]
adapter_type: str = "mistral_api"
endpoint: str = "https://api.mistral.ai/v1"
secret_reference: str = "secret://providers/mistral/eu-1"
region: str = "eu"
data_boundary: str = "eu"  # Data compliance region
concurrency_limit: int = 6  # Max samtidige requests
enabled: bool = True
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Forbindelser
- ✅ Kan deaktiveres
- ✅ Kan listes

#### 2.2 Deployments (Model deployments)

**API Endpoint:** `POST /api/v1/bot-governance/deployments`

```python
deployment_id: str = "mistral-large-eu-1"
connection_id: str = "connection-mistral-eu-1"
connection_version: int = 1
model_id: str = "mistral-large-latest"
model_family: str = "mistral-large"
max_context_tokens: int = 128000
max_output_tokens: int = 8192
structured_output: bool = True
tool_capabilities: list[str] = []  # ["function_calling", "web_search", etc.]
status: str = "active"  # [active, disabled, maintenance]
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Deployments
- ✅ Kan deaktiveres
- ✅ Kan listes

#### 2.3 Bot Profiles (Bot konfigurationer)

**API Endpoint:** `POST /api/v1/bot-governance/profiles`

```python
bot_profile_id: str = "architect-mistral-1"
agent_identity: str = "agent.architect.mistral.1"
display_name: str = "Architecture Bot 1"
deployment_id: str = "mistral-large-eu-1"
deployment_revision: int = 1
prompt_version: str = "architect-v1"
capabilities: list[str] = ["architecture.propose"]
permitted_tools: list[str] = []
data_policy: dict = {
    "boundary": "eu",
    "allowed_regions": ["eu"],
    "source_code_allowed": True,
}
budget_policy: dict = {
    "max_cost_minor_units": 500,  # Max tokens/minor units
    "max_input_tokens": 32000,
    "max_output_tokens": 4096,
}
concurrency_limit: int = 1
enabled: bool = True
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Botprofiler
- ✅ Kan deaktiveres
- ✅ Kan listes

#### 2.4 Roles (Bot roller)

**API Endpoint:** `POST /api/v1/bot-governance/roles`

```python
role_id: str = "chief-architect"
name: str = "Chief Architect"
purpose: str = "Create the primary architecture proposal"
protocol_function: str = "proposal"  # [proposal, review, implementation, etc.]
required_capabilities: list[str] = ["architecture.propose"]
output_schema_ref: str = "schema://architecture/proposal/v1"
rubric_ref: str = "rubric://architecture/v1"
independent_verification: bool = True  # Kræver uafhængig verifikation
enabled: bool = True
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Roller
- ✅ Kan deaktiveres
- ✅ Kan listes

#### 2.5 Templates (Council templates)

**API Endpoint:** `POST /api/v1/bot-governance/templates`

```python
template_id: str = "architecture-council"
name: str = "Architecture council"
stages: list[dict] = [
    {
        "stage_id": "proposal",
        "protocol_function": "proposal",
        "role_versions": [["chief-architect", 1]],
        "minimum_assignments": 1,
        "maximum_assignments": 1,
        "parallel": False,
        "blocking": True,
    }
]
approved_by: str = "controller"
enabled: bool = True
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Council templates
- ✅ Kan deaktiveres
- ✅ Kan listes

#### 2.6 Allocations (Bot allokering til roller)

**API Endpoint:** `POST /api/v1/bot-governance/allocations`

```python
command_id: str = "configure-allocation-001"
allocation_id: str = "architecture-review-pool"
role_id: str = "chief-architect"
role_version: int = 1
members: list[dict] = [
    {
        "bot_profile_id": "architect-mistral-1",
        "bot_profile_version": 1,
        "preference_rank": 1,  # 1 = højeste prioritet
        "fallback_rank": None,  # Optional fallback
    }
]
independence_level: str = "provider"  # [provider, model, deployment]
autonomy_level: int = 2  # 0-3 (0=lav, 3=høj)
hard_constraints: dict = {}  # Specifikke constraints
approved_by: str = "controller"
enabled: bool = True
```

**GUI Kontrol:**
- ✅ Kan oprettes via Multi-bot Control Plane → Allokering
- ✅ Kan listes

#### 2.7 Selections (Bot udvælgelse til runs)

**API Endpoint:** `POST /api/v1/bot-selections`

```python
command_id: str = "select-bots-001"
run_id: str = "run-001"
template_id: str = "architecture-council"
template_version: int = 1
allocation_refs: list[list] = [["architecture-review-pool", 1]]
scope_id: str = "project-001"
repository: str = "owner/repository"
base_sha: str = "0" * 40  # Git commit hash
requirements_fingerprint: str = "..."  # 64-char hash
architecture_fingerprint: str = "..."
contract_fingerprint: str = "..."
input_fingerprint: str = "..."
```

---

### 3. System Generator & Workflow Parametre

#### 3.1 Vision & Requirements

**GUI Form (Trin 1):**
```python
system_name: str = "Order Service"
goal: str = "Accepter og fuldfør ordrer med audit-spor"
features: list[str] = ["Order creation", "Order tracking", "Audit logging"]
tech_wishes: list[str] = ["Python", "FastAPI", "Postgres", "Hexagonal"]
constraints: list[str] = ["GDPR compliant", "Max latency < 100ms", "No vendor lock-in"]
priority: str = "high"  # [low, medium, high, critical]
```

#### 3.2 Architecture Decisions (HITL)

**GUI Form (Trin 3):**
```python
style: str = "hexagonal"  # [hexagonal, layered, modular_monolith, event_driven]
data_store: str = "postgresql"  # [postgresql, postgresql+redis, sqlite_dev_only]
auth: str = "oauth2_pkce"  # [oauth2_pkce, session_cookie, mtls_service]
notes: str = "Controller-noter / ADR-kommentar"
controller_choice: str = None  # APPROVE_RECOMMENDATION, CUSTOM_ARCHITECTURE, REQUEST_MORE_ANALYSIS
```

#### 3.3 Workflow Configuration

**API Endpoint:** `POST /workflows`

```python
name: str = "Order Processing Workflow"
description: str = "Workflow for at håndtere ordrebehandling"
intent_id: str = None  # Optional
template_id: str = None  # Optional
```

**Workflow States:**
```python
current_state: str  # [draft, active, paused, completed, failed]
```

**Workflow Transition:**
```python
command_id: str = "transition-001"
workflow_id: str = "workflow-001"
organization_id: str = "dor-org"
new_state: str = "active"  # Target state
```

---

### 4. Swarm Fleet Monitor Parametre

#### 4.1 Swarm Control

**API Endpoints:**
- `POST /api/v1/swarm/projects` - Start nytt swarm project
- `POST /api/v1/swarm/workers/claim` - Claim næste task
- `POST /api/v1/swarm/workers/heartbeat` - Forlæng lease
- `POST /api/v1/swarm/workers/complete` - Rapportér success/failure
- `POST /api/v1/swarm/pause` - Pause entire swarm
- `POST /api/v1/swarm/resume` - Resume paused swarm

**GUI Kontrol:**
- ✅ Pause/Resume swarm
- ✅ Genstart individuelle bot tasks
- ✅ Tving Controller Review (pause alle bots)
- ✅ Simuler aktivitet

#### 4.2 Task Queue Parametre

```python
# Start Project Request
project_id: str = "project-001"
requirements: dict = {}
tasks: list[dict] = [
    {
        "task_id": "task-001",
        "name": "Domain modeling",
        "capabilities": ["domain", "code"],
        "metadata": {
            "organization_id": "dor-org",
            "project_id": "project-001"
        }
    }
]
```

**Claim Request:**
```python
capabilities: list[str] = ["domain", "code"]
```

**Heartbeat Request:**
```python
task_id: str = "task-001"
capabilities: list[str] = ["domain", "code"]
```

**Complete Request:**
```python
task_id: str = "task-001"
success: bool = True
patch_result: dict = None  # Result data
error: str = None  # Error message
```

---

### 5. Agent & Task Configuration

#### 5.1 Agent Contracts

**Domain Model:**
```python
schema_version: str = "1.0"
contract_id: str = "contract-001"
role: str = "development"  # [development, test, audit, security, documentation, project_management, distribution]
objective: str = "Develop domain models"
source_requirements_fingerprint: str = "..."
source_architecture_fingerprint: str = "..."
required_inputs: list[str] = ["requirements", "architecture"]
permitted_outputs: list[str] = ["domain_models", "tests"]
forbidden_actions: list[str] = ["subprocess.Popen", "os.system"]
acceptance_criteria_ids: list[str] = ["criteria-001"]
instructions: list[str] = ["Follow hexagonal architecture", "Use type hints"]
```

#### 5.2 Agent Identities

```python
agent_id: str = "agent-001"
name: str = "Architecture Bot"
role: str = "architect"
model: str = "mistral-large"
capabilities: list[str] = ["architecture.propose", "code.review"]
concurrency_limit: int = 1
max_tokens: int = 32000
budget: float = 50.0  # USD per run
```

#### 5.3 Task Configuration

**Domain Model:**
```python
task_id: str = "task-001"
name: str = "Domain modeling"
description: str = "Create domain models for order system"
status: str = "PENDING"  # [PENDING, READY, CLAIMED, RUNNING, SUCCEEDED, FAILED, BLOCKED, CANCELLED, RETRYING]
priority: str = "HIGH"  # [LOW, MEDIUM, HIGH, CRITICAL]
dependency_status: str = "WAITING_FOR_DEPENDENCY"  # [WAITING_FOR_DEPENDENCY, READY]
workflow_id: str = "workflow-001"
organization_id: str = "dor-org"
dependencies: list[str] = ["task-002"]
assigned_actor: str = None  # Agent ID
retry_count: int = 0
max_retries: int = 3
last_error: str = None
execution_parameters: dict = {}
metadata: dict = {}
```

---

### 6. Pipeline Configuration

#### 6.1 Pipeline Start

**API Endpoint:** `POST /pipeline/start`

```python
requirements_yaml: str = """
project:
  name: Order Service
  description: Order processing system
  version: 1.0.0
requirements:
  - functional: [order_creation, order_tracking]
  - non_functional: [gdpr_compliance, low_latency]
architecture:
  style: hexagonal
  data_store: postgresql
  auth: oauth2_pkce
"""
```

#### 6.2 Pipeline Status

**API Endpoint:** `GET /pipeline/{workflow_id}`

**Response:**
```python
workflow_id: str
name: str
current_state: str
status: str
progress: float  # 0-1
created_at: str
tasks: list[dict] = [
    {
        "task_id": "task-001",
        "name": "Requirements analysis",
        "status": "COMPLETED",
        "assignee": "PM Agent",
        "started_at": "2024-01-01T00:00:00Z",
        "completed_at": "2024-01-01T00:05:00Z"
    }
]
```

#### 6.3 Pipeline Advance

**API Endpoint:** `POST /pipeline/{workflow_id}/advance`

Manually advance pipeline after gate approval.

---

### 7. Operations & Monitoring Parametre

#### 7.1 Operations Metrics (Monitorerbar)

**API Endpoint:** `GET /api/v1/swarm/ops/snapshot`

**Response:**
```python
captured_at: str  # ISO timestamp
status: str  # [ok, degraded, down]
queue:
  depth_by_status: dict = {
      "pending": 12,
      "claimed": 4,
      "running": 6,
      "completed": 40,
      "failed": 2
  }
  depth_by_capability: dict = {
      "domain": 3,
      "code": 8,
      "test": 5,
      "security": 2,
      "arch": 1
  }
  total_open: int = 22
workers:
  active: int = 6
  total: int = 10
dlq:
  size: int = 2
circuit_breakers: dict = {
    "gatekeeper": "closed",
    "sandbox": "closed",
    "external_llm": "half_open",
    "artifact_store": "closed"
}
performance:
  avg_task_seconds: float = 42.5
  p95_task_seconds: float = 120.0
  throughput_tasks_per_min: float = 3.2
  claim_latency_ms: float = 18.0
cost:
  tokens_used_total: float = 125000.0
  estimated_usd: float = 4.75
  budget_usd: float = 50.0
  budget_remaining_usd: float = 45.25
components:
  queue: str = "ok"
  workers: str = "ok"
  gatekeeper: str = "ok"
  sentinel: str = "ok"
  healer: str = "ok"
  dlq: str = "degraded"
  circuit_breakers: str = "ok"
  cost_optimizer: str = "ok"
```

**GUI Monitorering:**
- ✅ Swarm Fleet Monitor → Overview
- ✅ Swarm Fleet Monitor → WBS fremdrift
- ✅ Swarm Fleet Monitor → Sandkasse / Gate log
- ✅ Overblik & Systemtilstand

#### 7.2 Health Check

**API Endpoints:**
- `GET /health` - Liveness check
- `GET /health/ready` - Readiness check (inkl. database)

**Response:**
```python
status: str = "ok"  # eller "error"
database: str = "ok"  # eller "error"
migration_head: str = "..."  # Aktuel migration version
```

#### 7.3 Prometheus Metrics

**API Endpoint:** `GET /api/v1/swarm/ops/metrics`

**Metrics:**
```
# Queue metrics
swarm_queue_depth{status="pending"} 12
swarm_queue_depth{status="claimed"} 4
swarm_queue_depth_by_capability{capability="domain"} 3

# Worker metrics
swarm_workers_active 6
swarm_workers_total 10

# DLQ metrics
swarm_dlq_size 2

# Circuit breaker metrics
swarm_circuit_breaker{name="gatekeeper",state="closed"} 0

# Performance metrics
swarm_task_duration_seconds{quantile="avg"} 42.5
swarm_task_duration_seconds{quantile="0.95"} 120.0
swarm_throughput_tasks_per_min 3.2
swarm_claim_latency_ms 18.0

# Cost metrics
swarm_cost_usd{kind="estimated"} 4.75
swarm_cost_usd{kind="budget"} 50.0
swarm_cost_usd{kind="remaining"} 45.25
swarm_tokens_used_total 125000.0
```

---

### 8. Decision Cockpit Parametre

#### 8.1 Decision Configuration

```python
decision_id: str = "dec-arch-001"
title: str = "Arkitektur: Database persistens-strategi"
category: str = "ARCHITECTURE"  # [ARCHITECTURE, SECURITY, QA, PM, DEVELOPMENT]
risk: str = "HIGH"  # [CRITICAL, HIGH, MEDIUM, LOW]
status: str = "HUMAN_REQUIRED"  # [HUMAN_REQUIRED, PROPOSED, APPROVED, REJECTED]
question: str = "Hvilken primær lagringsmodel skal anvendes..."
```

#### 8.2 Agent Votes

```python
votes: list[dict] = [
    {
        "role": "Architect-Bot",
        "choice": "PostgreSQL JSONB",
        "confidence": "95%",
        "rationale": "Sikrer ACID og skalerbar AST-struktur."
    }
]
```

#### 8.3 Alternatives

```python
alternatives: list[dict] = [
    {
        "key": "POSTGRESQL",
        "title": "PostgreSQL med native JSONB",
        "pros": ["ACID-compliance", "Skalerbar AST"],
        "cons": ["Kræver ekstern database-instans"],
        "risk": "LOW"
    }
]
```

#### 8.4 Controller Decision

```python
choice: str = "POSTGRESQL"  # Valgt alternativ
rationale: str = "Bedste balance mellem funktion og drift"
```

---

### 9. Project & Control Plane Parametre

#### 9.1 Project Configuration

**API Endpoint:** `POST /api/v1/control-plane/projects`

```python
command_id: str = "create-project-001"
organization_id: str = "dor-org"
name: str = "Order Service Project"
description: str = "System for ordrebehandling"
intent: dict = {
    "goal": "Accepter og fuldfør ordrer med audit-spor",
    "description": "Komplet ordrebehandlingssystem",
    "priority": "high",
    "constraints": {
        "gdpr": True,
        "max_latency": 100
    },
    "required_capabilities": ["domain", "code", "test"]
}
```

#### 9.2 Project Launch

**API Endpoint:** `POST /api/v1/control-plane/projects/{project_id}/launch`

```python
command_id: str = "launch-project-001"
organization_id: str = "dor-org"
project_id: str = "project-001"
expected_project_fingerprint: str = "..."
```

#### 9.3 Project Status

**API Endpoint:** `GET /api/v1/control-plane/projects/{project_id}`

**Response:**
```python
project_id: str
organization_id: str
name: str
description: str
status: str  # [draft, launched, active, paused, completed, failed]
project_fingerprint: str
intent: dict
created_by: str
created_at: str
updated_at: str
launched_by: str
launched_at: str
launch_request_fingerprint: str
launch_command_id: str
revision: int
```

#### 9.4 Project Events

**API Endpoint:** `GET /api/v1/control-plane/projects/{project_id}/events`

**Query Parameters:**
```python
after_sequence: int = 0
limit: int = 100  # Max 100
include_authorization_audit: bool = True
```

**Response:**
```python
project_id: str
events: list[dict] = [
    {
        "event_id": "event-001",
        "event_type": "ProjectCreated",
        "aggregate_id": "project-001",
        "organization_id": "dor-org",
        "actor_id": "user-001",
        "occurred_at": "2024-01-01T00:00:00Z",
        "correlation_id": "...",
        "causation_id": "...",
        "sequence": 1,
        "metadata": {},
        "event_fingerprint": "..."
    }
]
next_after_sequence: int
```

---

## 📊 Monitorerbare Metrics

### 1. Swarm Metrics

| Metric | Type | Beskrivelse | GUI Sektion |
|--------|------|-------------|-------------|
| `swarm_queue_depth` | Gauge | Tasks in queue by status | Swarm Monitor → Overview |
| `swarm_queue_depth_by_capability` | Gauge | Queue depth by capability | Swarm Monitor → Overview |
| `swarm_workers_active` | Gauge | Number of busy workers | Swarm Monitor → Overview |
| `swarm_workers_total` | Gauge | Configured worker slots | Swarm Monitor → Overview |
| `swarm_dlq_size` | Gauge | Dead-letter queue size | Swarm Monitor → Overview |
| `swarm_circuit_breaker` | Gauge | Circuit breaker state | Operations Metrics |
| `swarm_task_duration_seconds` | Gauge | Task duration (avg, p95) | Operations Metrics |
| `swarm_throughput_tasks_per_min` | Gauge | Tasks completed per minute | Operations Metrics |
| `swarm_claim_latency_ms` | Gauge | Task claim latency | Operations Metrics |
| `swarm_cost_usd` | Gauge | Estimated spend | Operations Metrics |
| `swarm_tokens_used_total` | Counter | LLM tokens consumed | Operations Metrics |

### 2. Task Metrics

| Metric | Type | Beskrivelse | GUI Sektion |
|--------|------|-------------|-------------|
| Total tasks | Counter | Total number of tasks | Overblik & Systemtilstand |
| Completed tasks | Counter | Successfully completed tasks | Swarm Monitor → WBS |
| Failed tasks | Counter | Failed tasks | Swarm Monitor → Overview |
| In-progress tasks | Gauge | Currently running tasks | Swarm Monitor → WBS |
| Pending tasks | Gauge | Tasks waiting to start | Swarm Monitor → WBS |
| Blocked tasks | Gauge | Tasks blocked by dependencies | Swarm Monitor → WBS |

### 3. Agent Metrics

| Metric | Type | Beskrivelse | GUI Sektion |
|--------|------|-------------|-------------|
| Active agents | Gauge | Number of active agents | Overblik & Systemtilstand |
| Idle agents | Gauge | Number of idle agents | Swarm Monitor → Overview |
| Busy agents | Gauge | Number of busy agents | Swarm Monitor → Overview |
| Blocked agents | Gauge | Number of blocked agents | Swarm Monitor → Overview |
| CPU usage | Gauge | CPU percentage per agent | Swarm Monitor → Overview |
| Heartbeat | Timestamp | Last heartbeat per agent | Swarm Monitor → Overview |

### 4. System Metrics

| Metric | Type | Beskrivelse | GUI Sektion |
|--------|------|-------------|-------------|
| System status | Status | Overall system health | Overblik & Systemtilstand |
| Database status | Status | Database connectivity | Overblik & Systemtilstand |
| API status | Status | API endpoint health | Overblik & Systemtilstand |
| Migration head | Version | Current migration version | Health Check |

---

## 🔄 Data Flow & Integration

### API → Dashboard Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                    STREAMLIT DASHBOARD                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Multi-bot Control│  │ System Generator │  │ Swarm Monitor    │  │
│  │ Plane            │  │ & Workflow       │  │                  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
└───────────┼────────────────────┼────────────────────┼─────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND (api:8000)                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ /api/v1/bot-    │  │ /workflows       │  │ /api/v1/swarm   │  │
│  │ governance/*     │  │                   │  │ /*               │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                  │                     │              │
│  ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐  │
│  │ Bot Catalog      │  │ Workflow         │  │ Swarm Task      │  │
│  │ Service          │  │ Service          │  │ Queue           │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PERSISTENCE & INFRASTRUCTURE                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ PostgreSQL       │  │ MinIO            │  │ Redis            │  │
│  │ (Database)       │  │ (Artifacts)      │  │ (Queue)          │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Authentication Flow

```
1. Dashboard → Login (DOR_ADMIN_PASSWORD)
2. Dashboard → Get Token (DOR_API_TOKEN)
3. Dashboard → API Requests with Bearer Token
4. FastAPI → Validate JWT (DOR_JWT_SECRET_KEY)
5. FastAPI → Check Organization Context
6. FastAPI → Authorize Capabilities
7. FastAPI → Execute Command / Query
8. FastAPI → Return Response
```

---

## 📝 Implementations Plan for feature/gui-live-api

### Trin 1: Opret Branch
```bash
cd /workspace/github__smoeberg__kodegenerator
git checkout -b feature/gui-live-api
```

### Trin 2: Konfigurer API Forbindelse i Dashboard

**app.py - Global API Client:**
```python
# Tilføj i app.py
DOR_API_BASE = os.getenv("DOR_API_BASE", "http://api:8000")
DOR_API_TOKEN = os.getenv("DOR_API_TOKEN", "")
DOR_ORG_ID = os.getenv("DOR_ORG_ID", "dor-org")

# Opret API client helper
def get_api_client():
    from dashboard.control_plane_api import ControlPlaneAPI
    return ControlPlaneAPI(DOR_API_BASE, DOR_API_TOKEN, DOR_ORG_ID)
```

### Trin 3: Opdater Sektioner til Live Data

#### 3.1 Multi-bot Control Plane
- ✅ Allerede implementeret med ControlPlaneAPI
- ⚠️ Skal opdateres til at bruge live endpoints

#### 3.2 System Generator & Workflow
- ⚠️ Erstat mock data med live API calls til:
  - `/workflows` - Opret og hent workflows
  - `/pipeline` - Start og monitor pipelines

#### 3.3 Swarm Fleet Monitor
- ⚠️ Erstat mock data med live API calls til:
  - `/api/v1/swarm/projects` - Hent projects
  - `/api/v1/swarm/workers/claim` - Claim tasks
  - `/api/v1/swarm/ops/snapshot` - Hent metrics
  - `/api/v1/swarm/pause` / `/resume` - Kontrol

#### 3.4 Decision Cockpit
- ⚠️ Integrer med:
  - `/api/v1/decisions` - Hent og opdater beslutninger

#### 3.5 Overblik & Systemtilstand
- ⚠️ Integrer med:
  - `/api/v1/swarm/ops/snapshot` - System metrics
  - `/health/ready` - System readiness

#### 3.6 Digitale Medarbejdere
- ⚠️ Integrer med:
  - `/api/v1/bot-governance/profiles` - Hent bot profiler

#### 3.7 Opgaver (Tasks)
- ⚠️ Integrer med:
  - `/api/v1/swarm/projects/{id}` - Hent task status

### Trin 4: Implementer Real-time Updates

**Brug Streamlit's `st.rerun()` og caching:**
```python
import time

# Auto-refresh hver 5. sekund
if st.checkbox("Auto-refresh", value=True):
    time.sleep(5)
    st.rerun()
```

**Eller brug WebSocket for real-time:**
```python
# Connect til /api/v1/swarm/websocket for live updates
```

### Trin 5: Error Handling & Fallback

```python
try:
    # Live API call
    data = api_client.get("/api/v1/swarm/ops/snapshot")
except ControlPlaneAPIError as e:
    st.warning(f"Live API ikke tilgængelig: {e}")
    # Fallback til mock data
    data = _get_mock_data()
```

---

## 🎯 Nøgle Integration Points

### 1. API Client Configuration
- **Sti:** `dashboard/control_plane_api.py`
- **Status:** ✅ Eksisterer
- **Brug:** Multi-bot Control Plane

### 2. Swarm API Client
- **Sti:** Mangler
- **Action:** Opret ny client for `/api/v1/swarm/*`

### 3. Workflow API Client
- **Sti:** Mangler
- **Action:** Opret ny client for `/workflows`

### 4. Operations Metrics Client
- **Sti:** Mangler
- **Action:** Opret ny client for `/api/v1/swarm/ops/*`

---

## 📊 Sammenfatning af Alle Parametre

### Konfigurerbare (Can be changed via GUI/API):

| Category | Count | Description |
|----------|-------|-------------|
| System Configuration | 15+ | Miljøvariable, database, API, security |
| Bot Governance | 50+ | Connections, deployments, profiles, roles, templates, allocations |
| Workflow | 10+ | Workflow creation, transitions, states |
| Pipeline | 10+ | Pipeline start, advance, status |
| Swarm Control | 10+ | Pause, resume, claim, complete |
| Agent Contracts | 20+ | Contracts, packages, identities |
| Task Configuration | 15+ | Task parameters, dependencies, retries |
| Decision Cockpit | 10+ | Decisions, votes, alternatives |
| **Total** | **130+** | **Konfigurerbare parametre** |

### Monitorerbare (Can be monitored via GUI/API):

| Category | Count | Description |
|----------|-------|-------------|
| Operations Metrics | 20+ | Queue, workers, DLQ, circuit breakers, performance, cost |
| Task Metrics | 10+ | Status, progress, counts |
| Agent Metrics | 10+ | Status, CPU, heartbeat |
| System Metrics | 5+ | Health, readiness, migration |
| **Total** | **45+** | **Monitorerbare metrics** |

---

## 🔗 API Endpoint Reference

### Control Plane API (`/api/v1/control-plane`)
- `POST /projects` - Opret project
- `POST /projects/{id}/launch` - Launch project
- `GET /projects/{id}` - Hent project
- `GET /projects/{id}/events` - Hent project events

### Bot Governance API (`/api/v1/bot-governance`)
- `POST /connections` - Opret connection
- `GET /connections` - List connections
- `POST /connections/{id}/disable` - Deaktivér connection
- `POST /deployments` - Opret deployment
- `GET /deployments` - List deployments
- `POST /deployments/{id}/disable` - Deaktivér deployment
- `POST /profiles` - Opret profile
- `GET /profiles` - List profiles
- `POST /profiles/{id}/disable` - Deaktivér profile
- `POST /roles` - Opret role
- `GET /roles` - List roles
- `POST /roles/{id}/disable` - Deaktivér role
- `POST /templates` - Opret template
- `GET /templates` - List templates
- `POST /templates/{id}/disable` - Deaktivér template
- `POST /allocations` - Opret allocation
- `GET /allocations/{id}` - Hent allocation
- `POST /selections` - Opret selection
- `GET /selections/{id}` - Hent selection

### Swarm API (`/api/v1/swarm`)
- `POST /projects` - Start swarm project
- `GET /projects/{id}` - Hent project status
- `POST /workers/claim` - Claim task
- `POST /workers/heartbeat` - Heartbeat
- `POST /workers/complete` - Complete task
- `POST /pause` - Pause swarm
- `POST /resume` - Resume swarm

### Swarm Operations API (`/api/v1/swarm/ops`)
- `GET /snapshot` - Full state snapshot
- `GET /metrics` - Prometheus metrics
- `GET /health` - Health status

### Workflow API (`/workflows`)
- `POST /` - Opret workflow
- `GET /{id}` - Hent workflow
- `POST /{id}/transition` - Transition workflow

### Pipeline API (`/pipeline`)
- `POST /start` - Start pipeline
- `GET /{id}` - Hent pipeline status
- `POST /{id}/advance` - Advance pipeline
- `GET /` - List pipelines

### Bot Evidence API (`/api/v1/bot-evidence`)
- `GET /{type}/{id}` - Hent evidens

### Decisions API (`/api/v1/decisions`)
- `GET /` - List decisions
- `POST /` - Opret decision
- `GET /{id}` - Hent decision
- `POST /{id}/approve` - Godkend decision
- `POST /{id}/reject` - Afvis decision

---

## 📌 Næste Skridt

1. **Opret branch:** `feature/gui-live-api`
2. **Implementer API clients** for alle manglende endpoints
3. **Opdater dashboard sektioner** til at bruge live data
4. **Test forbindelser** til `http://api:8000`
5. **Implementer error handling** med graceful fallback
6. **Tilføj auto-refresh** for real-time monitoring
7. **Dokumenter integration** i README

---

*Dokument oprettet: 2024*
*Version: 1.0*
*Status: Draft (Under udvikling)*
