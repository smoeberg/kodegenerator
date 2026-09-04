# GUI Control Matrix - Komplet Parameter Kortlægning

## 📋 Oversigt

Dette dokument indeholder den **komplette maskinlæsbare kontrakt** for DOR GUI'en, baseret på:
- Eksisterende API endpoints (`api/main.py`)
- Domain models (domain/*.py)
- Pydantic schemas (api/schemas/*.py)
- Streamlit dashboard struktur (dashboard/*.py)
- Brugerens 7-sektions model

---

## 🎯 GUI Sektioner & Arkitektur

```
                    STREAMLIT (Control/Visualization Client)
                       │
                       │ HTTP/HTTPS
                       ▼
              ┌─────────────────────────┐
              │   FastAPI :8000          │  ← Kanonisk HTTP Surface
              │   (api/main.py)          │
              └────────────┬────────────┘
                       │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │ EIRA Brain  │   │ Phase 7      │   │ Persistence  │
   │ Authority   │   │ Queue/Workers│   │ (PostgreSQL) │
   │ Agents      │   │ Execution    │   │ (MinIO)      │
   └─────────────┘   └─────────────┘   └─────────────┘
```

**Princip:** Streamlit er **KUN** en control/visualization client, IKKE et domain layer.

---

## 📊 GUI Control Matrix

### 🔹 Klassifikation Nøgle

| Symbol | Betydning | Beskrivelse |
|--------|-----------|-------------|
| ✅ | READ | Data kan vises i GUI |
| ✏️ | WRITE | Data kan ændres via GUI |
| ▶️ | ACTION | Handling kan startes/stoppes |
| 🔐 | AUTH | Kræver autorisation |
| 📡 | LIVE | Realtime updates via WebSocket/Events |
| 📊 | METRICS | Monitorerbar metric |
| 📝 | AUDIT | Skal logges i audit trail |
| ⚠️ | DANGER | Farlig operation, kræver bekræftelse |
| 🔄 | REPLAY | Kan replayeres |

---

## 🏢 Sektion 1: Organisation / Projects

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `organization_id` | string | Unik organisation identifikator | ✅ | ❌ | ✅ |
| `organization_name` | string | Organisationsnavn | ✅ | ❌ | ✅ |
| `project_id` | string | Unik projekt identifikator | ✅ | ❌ | ✅ |
| `project_name` | string | Projektnavn | ✅ | ❌ | ✅ |
| `project_description` | string | Projektbeskrivelse | ✅ | ❌ | ✅ |
| `project_status` | enum | Projekt status | ✅ | ❌ | ✅ |
| `active_agents_count` | integer | Antal aktive agenter i projekt | ✅ | ✅ | ✅ |
| `active_assignments` | integer | Antal aktive opgave-tildelinger | ✅ | ✅ | ✅ |
| `workers_count` | integer | Antal workers | ✅ | ✅ | ✅ |
| `queue_depth` | integer | Antal opgaver i kø | ✅ | ✅ | ✅ |
| `errors_count` | integer | Antal fejl | ✅ | ✅ | ✅ |
| `recent_activities` | list | Seneste aktiviteter | ✅ | ❌ | ✅ |
| `project_health` | enum | Projekt health status | ✅ | ✅ | ✅ |
| `project_throughput` | float | Tasks per time unit | ✅ | ✅ | ❌ |
| `project_backlog` | integer | Antal tilbageværende opgaver | ✅ | ✅ | ✅ |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `project_name` | string | "" | Max 128 chars | 🔐 | ✅ | Required |
| `project_description` | string | "" | Max 500 chars | 🔐 | ✅ | Optional |
| `project_status` | enum | "draft" | draft, active, paused, completed, archived | 🔐 | ✅ | State machine |
| `project_configuration` | dict | {} | JSON object | 🔐 | ✅ | Schema validation |
| `enabled_features` | list | [] | List of feature flags | 🔐 | ✅ | Known features only |
| `project_policies` | dict | {} | Project-specific policies | 🔐 | ✅ | Schema validation |
| `agent_attachments` | list | [] | List of agent IDs | 🔐 | ✅ | Valid agent IDs |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Opret project | `/api/v1/control-plane/projects` | POST | 🔐 | ❌ | ❌ | ✅ |
| Start project | `/api/v1/control-plane/projects/{id}/launch` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Pause project | `/api/v1/swarm/pause` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Resume project | `/api/v1/swarm/resume` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Stop project | `/api/v1/control-plane/projects/{id}/stop` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Archive project | `/api/v1/control-plane/projects/{id}/archive` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Genstart workflow | `/pipeline/{id}/advance` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Trigger execution | `/api/v1/swarm/projects` | POST | 🔐 | ⚠️ | ✅ | ✅ |

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Project Manager | Projekt-specifikke | ✅ | ✅ | ▶️ |
| Developer | Read-only | ✅ | ❌ | ❌ |
| Auditor | Read-only | ✅ | ❌ | ❌ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Project status update | `/api/v1/control-plane/projects/{id}` | Polling | 5s |
| Project events | `/api/v1/control-plane/projects/{id}/events` | Polling | 10s |
| Queue updates | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Worker status | `/api/v1/swarm/workers/claim` | Polling | 10s |

### Metrics (📊)

```prometheus
# Project metrics
dor_project_status{project_id,status} 1
dor_project_agents_total{project_id} 5
dor_project_tasks_total{project_id,status} 10
dor_project_throughput_tasks_per_min{project_id} 3.2
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| PROJECT_CREATED | Opret project | Full request | Permanent |
| PROJECT_LAUNCHED | Start project | Command + fingerprint | Permanent |
| PROJECT_PAUSED | Pause project | Actor + reason | Permanent |
| PROJECT_STOPPED | Stop project | Actor + reason | Permanent |
| PROJECT_ARCHIVED | Archive project | Actor + reason | Permanent |
| CONFIG_CHANGED | Ændr config | Old + new values | Permanent |

---

## 🤖 Sektion 2: Agents / Workforce

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `agent_id` | string | Unik agent identifikator | ✅ | ❌ | ✅ |
| `agent_name` | string | Agent navn/alias | ✅ | ❌ | ✅ |
| `agent_role` | enum | Rolle (architect, developer, qa, security, pm) | ✅ | ❌ | ✅ |
| `agent_capabilities` | list | Liste af evner | ✅ | ❌ | ✅ |
| `agent_status` | enum | Status (active, idle, busy, disabled) | ✅ | ✅ | ✅ |
| `agent_availability` | enum | Availability (available, unavailable, maintenance) | ✅ | ✅ | ✅ |
| `current_assignment` | dict | Nuværende opgave-tildeling | ✅ | ❌ | ✅ |
| `assignment_history` | list | Historik over tildelinger | ✅ | ❌ | ✅ |
| `last_activity` | datetime | Seneste aktivitet | ✅ | ✅ | ✅ |
| `last_heartbeat` | datetime | Seneste heartbeat | ✅ | ✅ | ✅ |
| `executing_worker` | string | Worker der eksekverer | ✅ | ❌ | ✅ |
| `success_rate` | float | Success rate (0-1) | ✅ | ✅ | ❌ |
| `failure_rate` | float | Failure rate (0-1) | ✅ | ✅ | ❌ |
| `retry_count` | integer | Antal retries | ✅ | ✅ | ❌ |
| `token_usage` | integer | Tokens brugt | ✅ | ✅ | ❌ |
| `model_usage` | string | Model i brug | ✅ | ❌ | ✅ |
| `latency_ms` | float | Gennemsnitlig latency | ✅ | ✅ | ❌ |
| `errors` | list | Fejl liste | ✅ | ❌ | ✅ |
| `current_context` | dict | Nuværende kontekst | ✅ | ❌ | ❌ |
| `current_project` | string | Nuværende projekt | ✅ | ❌ | ✅ |
| `current_task` | string | Nuværende opgave | ✅ | ❌ | ✅ |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `agent_name` | string | "" | Max 128 chars | 🔐 | ✅ | Required |
| `agent_role` | enum | None | AGENT_ROLES tuple | 🔐 | ✅ | Valid role |
| `agent_capabilities` | list | [] | Known capabilities | 🔐 | ✅ | Valid capabilities |
| `agent_metadata` | dict | {} | JSON object | 🔐 | ✅ | Schema validation |
| `enabled` | boolean | True | True/False | 🔐 | ✅ | - |
| `assignment_policies` | dict | {} | Assignment policies | 🔐 | ✅ | Schema validation |
| `model_configuration` | dict | {} | Model config | 🔐 | ✅ | Schema validation |
| `risk_level` | enum | "medium" | low, medium, high, critical | 🔐 | ✅ | Valid level |
| `verification_capabilities` | list | [] | Verification caps | 🔐 | ✅ | Valid caps |
| `concurrency_limit` | integer | 1 | 1-10 | 🔐 | ✅ | 1 ≤ x ≤ 10 |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Create agent | `/api/v1/bot-governance/profiles` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Disable agent | `/api/v1/bot-governance/profiles/{id}/disable` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Enable agent | `/api/v1/bot-governance/profiles/{id}/enable` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Assign task | `/api/v1/swarm/workers/claim` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Reassign task | `/api/v1/swarm/workers/complete` + reassign | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Stop assignment | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Request human intervention | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| View history | `/api/v1/bot-evidence/*` | GET | 🔐 | ❌ | ❌ | ✅ |
| Inspect context | Custom endpoint mangler | - | 🔐 | ❌ | ❌ | ✅ |

**⚠️ Mangler:**
- `POST /agents/{id}/stop-assignment`
- `POST /agents/{id}/request-human-intervention`
- `GET /agents/{id}/context`

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Agent Manager | Agent-specifikke | ✅ | ✅ | ▶️ |
| Developer | Read-only | ✅ | ❌ | ❌ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Agent status | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Agent heartbeat | `/api/v1/swarm/workers/heartbeat` | WebSocket | Real-time |
| Agent assignment | `/api/v1/swarm/workers/claim` | WebSocket | Real-time |

### Metrics (📊)

```prometheus
# Agent metrics
dor_agent_status{agent_id,status} 1
dor_agent_success_rate{agent_id} 0.95
dor_agent_failure_rate{agent_id} 0.05
dor_agent_tokens_used_total{agent_id} 125000
dor_agent_latency_ms{agent_id} 42.5
dor_agent_heartbeat_seconds{agent_id} 15
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| AGENT_CREATED | Opret agent | Full request | Permanent |
| AGENT_DISABLED | Deaktiver agent | Actor + reason | Permanent |
| AGENT_ENABLED | Aktiver agent | Actor + reason | Permanent |
| AGENT_CONFIG_CHANGED | Ændr config | Old + new values | Permanent |
| TASK_ASSIGNED | Tildel opgave | Agent + task + timestamp | Permanent |
| TASK_COMPLETED | Færdig opgave | Agent + task + result | Permanent |

---

## 📋 Sektion 3: Tasks / Assignments / Queue

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `task_id` | string | Unik task identifikator | ✅ | ❌ | ✅ |
| `task_title` | string | Task titel | ✅ | ❌ | ✅ |
| `task_description` | string | Task beskrivelse | ✅ | ❌ | ✅ |
| `project_id` | string | Tilknyttet projekt | ✅ | ❌ | ✅ |
| `assigned_agent` | string | Tildelt agent | ✅ | ❌ | ✅ |
| `assignment_state` | enum | Tildelingsstatus | ✅ | ✅ | ✅ |
| `queue_state` | enum | Kø status | ✅ | ✅ | ✅ |
| `worker_id` | string | Worker der eksekverer | ✅ | ❌ | ✅ |
| `attempt` | integer | Forsøgsnummer | ✅ | ✅ | ❌ |
| `retry_count` | integer | Antal retries | ✅ | ✅ | ❌ |
| `created_at` | datetime | Oprettelsestid | ✅ | ❌ | ✅ |
| `started_at` | datetime | Starttid | ✅ | ❌ | ✅ |
| `updated_at` | datetime | Seneste update | ✅ | ❌ | ✅ |
| `completed_at` | datetime | Færdiggørelses tid | ✅ | ❌ | ✅ |
| `duration_ms` | float | Varighed i ms | ✅ | ✅ | ❌ |
| `lease_id` | string | Lease identifikator | ✅ | ❌ | ✅ |
| `lease_expiry` | datetime | Lease udløb | ✅ | ✅ | ❌ |
| `error` | string | Fejlmeddelelse | ✅ | ❌ | ✅ |
| `result` | dict | Resultat data | ✅ | ❌ | ✅ |
| `artifact_id` | string | Artefakt identifikator | ✅ | ❌ | ✅ |
| `dependencies` | list | Afhængigheder | ✅ | ❌ | ✅ |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `assignment` | string | None | Valid agent_id | 🔐 | ✅ | Valid agent |
| `priority` | enum | "medium" | low, medium, high, critical | 🔐 | ✅ | Valid priority |
| `state` | enum | "pending" | TaskStatus enum | 🔐 | ✅ | State machine |
| `retry_policy` | dict | {} | Retry policy | 🔐 | ✅ | Schema validation |
| `scheduling` | dict | {} | Scheduling config | 🔐 | ✅ | Schema validation |
| `metadata` | dict | {} | Custom metadata | 🔐 | ✅ | JSON validation |
| `dependencies` | list | [] | Task IDs | 🔐 | ✅ | Valid task IDs |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Create task | `/api/v1/swarm/projects` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Assign task | `/api/v1/swarm/workers/claim` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Reassign task | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Start task | Implicit via claim | - | 🔐 | ⚠️ | ✅ | ✅ |
| Pause task | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Cancel task | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Retry task | `/api/v1/swarm/workers/complete` + retry | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Force retry | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Escalate task | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |
| Inspect task | `/api/v1/swarm/projects/{id}` | GET | 🔐 | ❌ | ❌ | ✅ |
| Replay task | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |

**⚠️ Mangler:**
- `POST /tasks/{id}/reassign`
- `POST /tasks/{id}/pause`
- `POST /tasks/{id}/cancel`
- `POST /tasks/{id}/retry`
- `POST /tasks/{id}/force-retry`
- `POST /tasks/{id}/escalate`
- `POST /tasks/{id}/replay`

### Queue Monitor (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `queue_depth` | integer | Total opgaver i kø | ✅ | ✅ | ❌ |
| `pending_count` | integer | Opgaver der venter | ✅ | ✅ | ❌ |
| `running_count` | integer | Opgaver under eksekvering | ✅ | ✅ | ❌ |
| `completed_count` | integer | Færdige opgaver | ✅ | ✅ | ❌ |
| `failed_count` | integer | Fejlede opgaver | ✅ | ✅ | ❌ |
| `dlq_count` | integer | Dead-letter queue | ✅ | ✅ | ❌ |
| `retry_backlog` | integer | Retry backlog | ✅ | ✅ | ❌ |
| `lease_expired` | integer | Udløbte leases | ✅ | ✅ | ⚠️ |
| `worker_capacity` | integer | Worker kapacitet | ✅ | ✅ | ❌ |

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Project Manager | Projekt-specifikke | ✅ | ✅ | ▶️ |
| Task Manager | Task-specifikke | ✅ | ✅ | ▶️ |
| Developer | Read-only | ✅ | ❌ | ❌ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Task status | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Queue depth | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Task assignment | `/api/v1/swarm/workers/claim` | WebSocket | Real-time |
| Task completion | `/api/v1/swarm/workers/complete` | WebSocket | Real-time |

### Metrics (📊)

```prometheus
# Queue metrics
dor_queue_depth{queue_type} 25
dor_queue_pending_tasks 12
dor_queue_running_tasks 6
dor_queue_completed_tasks 40
dor_queue_failed_tasks 2
dor_queue_dlq_size 1
dor_queue_retry_backlog 3

# Task metrics
dor_task_duration_ms{task_id} 42500
dor_task_attempts_total{task_id} 3
dor_task_success_total{task_id} 1
dor_task_failure_total{task_id} 2
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| TASK_CREATED | Opret task | Full request | Permanent |
| TASK_ASSIGNED | Tildel task | Agent + task + timestamp | Permanent |
| TASK_STARTED | Start task | Worker + task + timestamp | Permanent |
| TASK_COMPLETED | Færdig task | Result + duration | Permanent |
| TASK_FAILED | Fejl task | Error + retry_count | Permanent |
| TASK_RETRIED | Retry task | Attempt number | Permanent |
| TASK_CANCELLED | Annuller task | Actor + reason | Permanent |
| ASSIGNMENT_CHANGED | Ændr tildeling | Old + new agent | Permanent |

---

## 🧠 Sektion 4: Brain / Knowledge / Epistemics

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `observation_id` | string | Unik observation ID | ✅ | ❌ | ✅ |
| `observation_data` | dict | Observationsdata | ✅ | ❌ | ✅ |
| `claim_id` | string | Unik claim ID | ✅ | ❌ | ✅ |
| `claim_statement` | string | Claim udsagn | ✅ | ❌ | ✅ |
| `evidence_id` | string | Unik evidence ID | ✅ | ❌ | ✅ |
| `evidence_data` | dict | Evidence data | ✅ | ❌ | ✅ |
| `verification_status` | enum | Verifikationsstatus | ✅ | ✅ | ✅ |
| `knowledge_state` | enum | Knowledge state | ✅ | ✅ | ✅ |
| `confidence` | float | Confidence score (0-1) | ✅ | ✅ | ❌ |
| `provenance` | dict | Provenance data | ✅ | ❌ | ✅ |
| `source` | string | Kilde | ✅ | ❌ | ✅ |
| `agent_id` | string | Agent der oprettede | ✅ | ❌ | ✅ |
| `timestamp` | datetime | Oprettelsestid | ✅ | ❌ | ✅ |
| `revision` | integer | Revisionsnummer | ✅ | ❌ | ✅ |
| `conflicts` | list | Konflikter | ✅ | ❌ | ✅ |
| `disputes` | list | Disputes | ✅ | ❌ | ✅ |
| `superseded_records` | list | Overskrevne records | ✅ | ❌ | ✅ |

### Knowledge State (📚)

| State | Beskrivelse | Transition | Auth Required |
|-------|-------------|------------|---------------|
| PROPOSED | Forslag fremsat | → DISPUTED, CONFIRMED | ❌ |
| DISPUTED | Under dispute | → PROPOSED, CONFIRMED, SUPERSEDED | 🔐 |
| CONFIRMED | Bekræftet | → SUPERSEDED | 🔐 |
| SUPERSEDED | Overskrevet | Terminal | 🔐 |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `verification_policy` | dict | {} | Verification policy | 🔐 | ✅ | Schema validation |
| `required_quorum` | integer | 1 | 1-5 | 🔐 | ✅ | 1 ≤ x ≤ 5 |
| `required_capabilities` | list | [] | Capability IDs | 🔐 | ✅ | Valid capabilities |
| `risk_threshold` | enum | "medium" | low, medium, high, critical | 🔐 | ✅ | Valid threshold |
| `escalation_policy` | dict | {} | Escalation policy | 🔐 | ✅ | Schema validation |
| `timeout_seconds` | integer | 300 | 60-3600 | 🔐 | ✅ | 60 ≤ x ≤ 3600 |
| `independence_requirement` | boolean | True | True/False | 🔐 | ✅ | - |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Submit observation | `/api/v1/bot-evidence/observations` | POST | 🔐 | ❌ | ❌ | ✅ |
| Propose claim | `/api/v1/bot-evidence/claims` | POST | 🔐 | ❌ | ❌ | ✅ |
| Attach evidence | `/api/v1/bot-evidence/*` | POST | 🔐 | ❌ | ❌ | ✅ |
| Request verification | `/api/v1/bot-evidence/verifications` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Dispute claim | `/api/v1/bot-evidence/disputes` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Confirm claim | `/api/v1/bot-evidence/confirmations` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Supersede claim | `/api/v1/bot-evidence/supersede` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Escalate to human | Custom endpoint mangler | - | 🔐 | ⚠️ | ✅ | ✅ |

**⚠️ Mangler:**
- `POST /brain/observations`
- `POST /brain/claims`
- `POST /brain/evidence`
- `POST /brain/verifications`
- `POST /brain/disputes`
- `POST /brain/confirmations`
- `POST /brain/supersede`
- `POST /brain/escalate`

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Knowledge Manager | Knowledge-specifikke | ✅ | ✅ | ▶️ |
| Verifier | Verifikation | ✅ | ✅ | ▶️ |
| Auditor | Read-only | ✅ | ❌ | ❌ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Knowledge state | `/api/v1/bot-evidence/*` | Polling | 10s |
| Verification status | `/api/v1/bot-evidence/*` | Polling | 10s |
| New observations | WebSocket | Real-time | - |
| New claims | WebSocket | Real-time | - |

### Metrics (📊)

```prometheus
# Knowledge metrics
dor_knowledge_state{state} 10
dor_knowledge_confidence{knowledge_id} 0.95
dor_knowledge_verification_time_seconds{knowledge_id} 42.5
dor_knowledge_disputes_total 2
dor_knowledge_superseded_total 1
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| OBSERVATION_SUBMITTED | Indsend observation | Full data + agent | Permanent |
| CLAIM_PROPOSED | Forslag claim | Claim + evidence | Permanent |
| EVIDENCE_ATTACHED | Tilføj evidence | Evidence + claim | Permanent |
| VERIFICATION_REQUESTED | Anmod verifikation | Claim + policy | Permanent |
| CLAIM_DISPUTED | Disput claim | Dispute + reason | Permanent |
| CLAIM_CONFIRMED | Bekræft claim | Claim + verifier | Permanent |
| CLAIM_SUPERSEDED | Overskriv claim | Old + new claim | Permanent |

---

## ⚖️ Sektion 5: Council / Verification / Authority

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `council_id` | string | Unik council ID | ✅ | ❌ | ✅ |
| `hypothesis` | string | Nuværende hypotese | ✅ | ❌ | ✅ |
| `council_round` | integer | Council runde | ✅ | ❌ | ✅ |
| `participants` | list | Deltagere | ✅ | ❌ | ✅ |
| `votes` | list | Stemmer | ✅ | ❌ | ✅ |
| `evidence` | list | Evidence | ✅ | ❌ | ✅ |
| `disputes` | list | Disputes | ✅ | ❌ | ✅ |
| `risk` | enum | Risikoniveau | ✅ | ✅ | ✅ |
| `verification_mode` | enum | Verifikationsmode | ✅ | ❌ | ✅ |
| `required_capability` | list | Krævede evner | ✅ | ❌ | ✅ |
| `required_votes` | integer | Krævede stemmer | ✅ | ❌ | ✅ |
| `independence` | enum | Uafhængighedsniveau | ✅ | ❌ | ✅ |
| `decision_readiness` | enum | Beslutningsberedskab | ✅ | ✅ | ✅ |
| `escalation` | dict | Escalation info | ✅ | ❌ | ✅ |
| `anti_tube_state` | enum | Anti-Tube status | ✅ | ✅ | ✅ |
| `failure_pattern` | list | Fejlmønstre | ✅ | ❌ | ✅ |
| `pivot_requirement` | boolean | Pivot krævet | ✅ | ❌ | ✅ |

### Council Roles (👥)

| Rolle | Beskrivelse | Protocol Function |
|-------|-------------|-------------------|
| Proposer | Fremkommer med forslag | proposal |
| Architect | Arkitektur specialist | architecture |
| Security Skeptic | Sikkerheds kritiker | security_review |
| QA Red Team | Kvalitetssikring | qa_review |
| Decision Readiness | Beslutningsberedskab | decision_readiness |
| Anti-Tube | Anti-tube mekanisme | anti_tube |

### Verification Modes (🔍)

| Mode | Beskrivelse | Required Quorum |
|------|-------------|-----------------|
| Deterministic | Deterministisk verifikation | 1 |
| Single-agent | Enkelt agent | 1 |
| Quorum | Flertal | Configurable (1-5) |
| Human escalation | Menneskelig escalation | 1 (human) |
| Dialectical | Dialektisk council | Configurable |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `verification_policy` | dict | {} | Policy config | 🔐 | ✅ | Schema validation |
| `required_quorum` | integer | 1 | 1-5 | 🔐 | ✅ | 1 ≤ x ≤ 5 |
| `required_capabilities` | list | [] | Capability IDs | 🔐 | ✅ | Valid capabilities |
| `risk_threshold` | enum | "medium" | low, medium, high, critical | 🔐 | ✅ | Valid threshold |
| `escalation_policy` | dict | {} | Escalation policy | 🔐 | ✅ | Schema validation |
| `timeout_seconds` | integer | 300 | 60-3600 | 🔐 | ✅ | 60 ≤ x ≤ 3600 |
| `independence_requirement` | enum | "provider" | provider, model, deployment | 🔐 | ✅ | Valid level |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Start verification | `/api/v1/bot-governance/verifications` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Start council | `/api/v1/bot-governance/councils` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Continue round | `/api/v1/bot-governance/councils/{id}/continue` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Resolve dispute | `/api/v1/bot-governance/disputes/{id}/resolve` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Escalate | `/api/v1/bot-governance/councils/{id}/escalate` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Approve | `/api/v1/decisions/{id}/approve` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Reject | `/api/v1/decisions/{id}/reject` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Pivot | `/api/v1/bot-governance/councils/{id}/pivot` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Halt | `/api/v1/bot-governance/councils/{id}/halt` | POST | 🔐 | ⚠️ | ✅ | ✅ |

**⚠️ Mangler:**
- `POST /council/verifications`
- `POST /council/councils`
- `POST /council/councils/{id}/continue`
- `POST /council/disputes/{id}/resolve`
- `POST /council/councils/{id}/escalate`
- `POST /council/councils/{id}/pivot`
- `POST /council/councils/{id}/halt`

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Council Manager | Council-specifikke | ✅ | ✅ | ▶️ |
| Verifier | Verifikation | ✅ | ✅ | ▶️ |
| Decider | Beslutninger | ✅ | ✅ | ▶️ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Council state | `/api/v1/bot-governance/councils/{id}` | Polling | 10s |
| Verification state | `/api/v1/bot-governance/verifications/{id}` | Polling | 10s |
| Votes | `/api/v1/bot-governance/councils/{id}/votes` | Polling | 10s |
| Council events | WebSocket | Real-time | - |

### Metrics (📊)

```prometheus
# Council metrics
dor_council_status{council_id,status} 1
dor_council_participants{council_id} 5
dor_council_votes{council_id,vote} 3
dor_council_round{council_id} 2
dor_council_risk{council_id} 1
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| VERIFICATION_STARTED | Start verifikation | Policy + claim | Permanent |
| COUNCIL_STARTED | Start council | Participants + hypothesis | Permanent |
| COUNCIL_ROUND_CONTINUED | Fortsæt runde | Round + votes | Permanent |
| DISPUTE_RESOLVED | Løs dispute | Resolution + reason | Permanent |
| COUNCIL_ESCALATED | Escaler council | Reason + level | Permanent |
| COUNCIL_APPROVED | Godkend council | Decision + votes | Permanent |
| COUNCIL_REJECTED | Afvis council | Reason + votes | Permanent |
| COUNCIL_PIVOTED | Pivot council | Old + new hypothesis | Permanent |
| COUNCIL_HALTED | Stop council | Reason + actor | Permanent |

---

## ⚙️ Sektion 6: Execution / Workers / Infrastructure

### Monitorér (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `worker_count` | integer | Antal workers | ✅ | ✅ | ✅ |
| `active_workers` | integer | Antal aktive workers | ✅ | ✅ | ✅ |
| `worker_health` | dict | Worker health status | ✅ | ✅ | ⚠️ |
| `cpu_usage` | float | CPU forbrug (%) | ✅ | ✅ | ❌ |
| `memory_usage` | float | Hukommelsesforbrug (MB) | ✅ | ✅ | ❌ |
| `queue_utilization` | float | Kø udnyttelse (%) | ✅ | ✅ | ❌ |
| `active_executions` | integer | Antal aktive eksekveringer | ✅ | ✅ | ✅ |
| `execution_latency` | float | Eksekveringslatency (ms) | ✅ | ✅ | ❌ |
| `failed_executions` | integer | Antal fejlede eksekveringer | ✅ | ✅ | ⚠️ |
| `retry_rate` | float | Retry rate (%) | ✅ | ✅ | ❌ |
| `lease_expirations` | integer | Antal udløbte leases | ✅ | ✅ | ⚠️ |
| `worker_crashes` | integer | Antal worker crashes | ✅ | ✅ | ⚠️ |
| `container_status` | dict | Container status | ✅ | ✅ | ⚠️ |
| `api_health` | dict | API health status | ✅ | ✅ | ⚠️ |
| `database_health` | dict | Database health | ✅ | ✅ | ⚠️ |
| `redis_health` | dict | Redis health | ✅ | ✅ | ⚠️ |
| `external_providers` | dict | Eksterne provider status | ✅ | ✅ | ⚠️ |
| `llm_availability` | dict | LLM tilgængelighed | ✅ | ✅ | ⚠️ |
| `deployment_status` | dict | Deployment status | ✅ | ✅ | ⚠️ |

### Worker Details (👷)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `worker_id` | string | Unik worker ID | ✅ | ❌ | ✅ |
| `host_container` | string | Host/container | ✅ | ❌ | ✅ |
| `started_at` | datetime | Starttid | ✅ | ❌ | ✅ |
| `last_heartbeat` | datetime | Seneste heartbeat | ✅ | ✅ | ✅ |
| `current_assignment` | dict | Nuværende opgave | ✅ | ❌ | ✅ |
| `current_agent` | string | Nuværende agent | ✅ | ❌ | ✅ |
| `cpu_percent` | float | CPU forbrug | ✅ | ✅ | ❌ |
| `memory_mb` | float | Hukommelse forbrug | ✅ | ✅ | ❌ |
| `execution_count` | integer | Antal eksekveringer | ✅ | ✅ | ❌ |
| `errors_count` | integer | Antal fejl | ✅ | ✅ | ❌ |
| `status` | enum | Worker status | ✅ | ✅ | ✅ |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `worker_concurrency` | integer | 1 | 1-10 | 🔐 | ✅ | 1 ≤ x ≤ 10 |
| `queue_settings` | dict | {} | Queue config | 🔐 | ✅ | Schema validation |
| `retry_policy` | dict | {} | Retry policy | 🔐 | ✅ | Schema validation |
| `lease_timeout` | integer | 300 | 60-3600 | 🔐 | ✅ | 60 ≤ x ≤ 3600 |
| `execution_limits` | dict | {} | Execution limits | 🔐 | ✅ | Schema validation |
| `provider_configuration` | dict | {} | Provider config | 🔐 | ✅ | Schema validation |
| `feature_flags` | dict | {} | Feature flags | 🔐 | ✅ | Known flags only |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| Drain worker | `/api/v1/swarm/workers/{id}/drain` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Restart worker | `/api/v1/swarm/workers/{id}/restart` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Pause queue | `/api/v1/swarm/pause` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Resume queue | `/api/v1/swarm/resume` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Retry failed job | `/api/v1/swarm/workers/complete` + retry | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Cancel execution | `/api/v1/swarm/workers/{id}/cancel` | POST | 🔐 | ⚠️ | ✅ | ✅ |
| Emergency stop | `/api/v1/swarm/emergency-stop` | POST | 🔐 | ⚠️⚠️ | ✅✅ | ✅ |

**⚠️ Mangler:**
- `POST /workers/{id}/drain`
- `POST /workers/{id}/restart`
- `POST /workers/{id}/cancel`
- `POST /swarm/emergency-stop`

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Operations Manager | Operations-specifikke | ✅ | ✅ | ▶️ |
| Developer | Read-only | ✅ | ❌ | ❌ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| Worker status | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Worker heartbeat | `/api/v1/swarm/workers/heartbeat` | WebSocket | Real-time |
| Queue status | `/api/v1/swarm/ops/snapshot` | Polling | 5s |
| Execution events | WebSocket | Real-time | - |

### Metrics (📊)

```prometheus
# Worker metrics
dor_worker_status{worker_id,status} 1
dor_worker_cpu_percent{worker_id} 45.5
dor_worker_memory_mb{worker_id} 512
dor_worker_executions_total{worker_id} 100
dor_worker_errors_total{worker_id} 5

# Queue metrics
dor_queue_utilization_percent 75.5
dor_queue_active_executions 6

# Execution metrics
dor_execution_latency_ms 42500
dor_execution_failures_total 2
dor_execution_retry_rate 0.05
```

### Audit (📝)

| Event Type | Trigger | Data Logget | Retention |
|------------|---------|-------------|-----------|
| WORKER_STARTED | Start worker | Worker + container | Permanent |
| WORKER_STOPPED | Stop worker | Worker + reason | Permanent |
| WORKER_CRASHED | Worker crash | Worker + error | Permanent |
| WORKER_DRAINED | Drain worker | Worker + actor | Permanent |
| WORKER_RESTARTED | Restart worker | Worker + actor | Permanent |
| QUEUE_PAUSED | Pause kø | Actor + reason | Permanent |
| QUEUE_RESUMED | Resume kø | Actor + reason | Permanent |
| EXECUTION_CANCELLED | Annuller eksekvering | Actor + reason | Permanent |
| EMERGENCY_STOP | Nødstop | Actor + reason | Permanent |

---

## 📈 Sektion 7: Monitoring / Audit / System Health

### System Health (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `api_uptime` | float | API uptime (%) | ✅ | ✅ | ❌ |
| `api_health` | dict | API health status | ✅ | ✅ | ⚠️ |
| `api_latency` | float | API latency (ms) | ✅ | ✅ | ❌ |
| `requests_per_sec` | float | Requests per sekund | ✅ | ✅ | ❌ |
| `error_rate` | float | Fejlrate (%) | ✅ | ✅ | ⚠️ |
| `http_4xx_count` | integer | Antal 4xx fejl | ✅ | ✅ | ❌ |
| `http_5xx_count` | integer | Antal 5xx fejl | ✅ | ✅ | ⚠️ |
| `database_connectivity` | boolean | Database forbindelse | ✅ | ✅ | ⚠️ |
| `queue_connectivity` | boolean | Kø forbindelse | ✅ | ✅ | ⚠️ |
| `worker_availability` | float | Worker tilgængelighed (%) | ✅ | ✅ | ❌ |
| `external_integrations` | dict | Eksterne integrationer | ✅ | ✅ | ⚠️ |
| `model_providers` | dict | Model provider status | ✅ | ✅ | ⚠️ |

### Performance (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `task_throughput` | float | Tasks per time unit | ✅ | ✅ | ❌ |
| `avg_execution_time` | float | Gennemsnitlig eksekveringstid (ms) | ✅ | ✅ | ❌ |
| `p50_latency` | float | P50 latency (ms) | ✅ | ✅ | ❌ |
| `p95_latency` | float | P95 latency (ms) | ✅ | ✅ | ❌ |
| `p99_latency` | float | P99 latency (ms) | ✅ | ✅ | ❌ |
| `queue_wait_time` | float | Kø ventetid (ms) | ✅ | ✅ | ❌ |
| `worker_utilization` | float | Worker udnyttelse (%) | ✅ | ✅ | ❌ |
| `agent_utilization` | float | Agent udnyttelse (%) | ✅ | ✅ | ❌ |
| `token_consumption` | integer | Tokens forbrugt | ✅ | ✅ | ❌ |
| `model_latency` | float | Model latency (ms) | ✅ | ✅ | ❌ |
| `cost_usd` | float | Omkostninger (USD) | ✅ | ✅ | ❌ |

### Reliability (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `failed_tasks` | integer | Antal fejlede tasks | ✅ | ✅ | ⚠️ |
| `failed_executions` | integer | Antal fejlede eksekveringer | ✅ | ✅ | ⚠️ |
| `retry_loops` | integer | Antal retry loops | ✅ | ✅ | ⚠️ |
| `lease_expirations` | integer | Antal udløbte leases | ✅ | ✅ | ⚠️ |
| `worker_crashes` | integer | Antal worker crashes | ✅ | ✅ | ⚠️ |
| `dlq_size` | integer | Dead-letter queue størrelse | ✅ | ✅ | ⚠️ |
| `stuck_assignments` | integer | Antal stuck assignments | ✅ | ✅ | ⚠️ |
| `api_failures` | integer | Antal API fejl | ✅ | ✅ | ⚠️ |
| `database_errors` | integer | Antal database fejl | ✅ | ✅ | ⚠️ |

### Security (✅)

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `auth_failures` | integer | Antal autentificeringsfejl | ✅ | ✅ | ⚠️ |
| `authz_failures` | integer | Antal autorisationsfejl | ✅ | ✅ | ⚠️ |
| `authority_decisions` | integer | Antal authority beslutninger | ✅ | ✅ | ✅ |
| `authority_grants` | integer | Antal authority grants | ✅ | ✅ | ✅ |
| `expired_grants` | integer | Antal udløbte grants | ✅ | ✅ | ⚠️ |
| `rejected_execution_requests` | integer | Antal afviste eksekveringsanmodninger | ✅ | ✅ | ⚠️ |
| `replay_attempts` | integer | Antal replay forsøg | ✅ | ✅ | ⚠️ |
| `suspicious_activity` | integer | Antal mistænkelige aktiviteter | ✅ | ✅ | ⚠️ |

### Audit (✅)

Alle væsentlige mutationer skal spores:

```
WHO
  ↓
DID WHAT
  ↓
TO WHICH RESOURCE
  ↓
WHEN
  ↓
WHY / COMMAND
  ↓
AUTHORITY
  ↓
RESULT
```

| Parameter | Type | Beskrivelse | Live | Metrics | Audit |
|-----------|------|-------------|------|---------|-------|
| `event_id` | string | Unik event ID | ✅ | ❌ | ✅ |
| `event_type` | enum | Event type | ✅ | ❌ | ✅ |
| `actor_id` | string | Hvem udførte handlingen | ✅ | ❌ | ✅ |
| `resource_id` | string | Hvilken ressource | ✅ | ❌ | ✅ |
| `timestamp` | datetime | Hvornår | ✅ | ❌ | ✅ |
| `command_id` | string | Hvilket command | ✅ | ❌ | ✅ |
| `authority_grant` | string | Authority grant | ✅ | ❌ | ✅ |
| `result` | enum | Resultat | ✅ | ❌ | ✅ |

### Kan ændres (✏️)

| Parameter | Type | Default | Allowed Values | Auth | Audit | Validation |
|-----------|------|---------|---------------|------|-------|------------|
| `audit_retention_days` | integer | 365 | 30-3650 | 🔐 | ✅ | 30 ≤ x ≤ 3650 |
| `audit_enabled` | boolean | True | True/False | 🔐 | ✅ | - |
| `metrics_enabled` | boolean | True | True/False | 🔐 | ✅ | - |
| `alert_thresholds` | dict | {} | Alert thresholds | 🔐 | ✅ | Schema validation |

### Handlinger (▶️)

| Handling | Endpoint | Method | Auth | Danger | Confirm | Audit |
|----------|----------|--------|------|--------|---------|-------|
| View audit log | `/api/v1/events` | GET | 🔐 | ❌ | ❌ | ✅ |
| Export audit log | `/api/v1/events/export` | GET | 🔐 | ❌ | ❌ | ✅ |
| Clear audit log | `/api/v1/events/clear` | POST | 🔐 | ⚠️⚠️ | ✅✅ | ✅ |
| View metrics | `/api/v1/swarm/ops/metrics` | GET | 🔐 | ❌ | ❌ | ❌ |
| Export metrics | `/api/v1/swarm/ops/metrics/export` | GET | 🔐 | ❌ | ❌ | ❌ |

**⚠️ Mangler:**
- `GET /events/export`
- `POST /events/clear`
- `GET /swarm/ops/metrics/export`

### Authority (🔐)

| Rolle | Tilladte Handlinger | Read | Write | Action |
|-------|-------------------|------|-------|--------|
| Controller | Alle | ✅ | ✅ | ✅ |
| Admin | Alle | ✅ | ✅ | ✅ |
| Auditor | Read-only | ✅ | ❌ | ❌ |
| Operations | Operations-specifikke | ✅ | ❌ | ▶️ |

### Live API (📡)

| Event | Endpoint | Type | Frequency |
|-------|----------|------|-----------|
| System health | `/health`, `/health/ready` | Polling | 10s |
| Metrics | `/api/v1/swarm/ops/metrics` | Polling | 10s |
| Audit events | WebSocket | Real-time | - |
| System events | WebSocket | Real-time | - |

### Metrics (📊)

```prometheus
# System health metrics
dor_api_uptime_seconds 86400
dor_api_health{component} 1
dor_api_latency_ms 18.5
dor_requests_total 1000
dor_error_rate 0.05

# Reliability metrics
dor_failed_tasks_total 2
dor_failed_executions_total 1
dor_retry_loops_total 3
dor_lease_expirations_total 1
dor_worker_crashes_total 0

# Security metrics
dor_auth_failures_total 5
dor_authz_failures_total 2
dor_authority_decisions_total 10
```

---

## 📋 Mangler Liste (Critical)

### API Endpoints der mangler for fuld GUI integration:

#### Sektion 2: Agents / Workforce
- [ ] `POST /agents/{id}/stop-assignment`
- [ ] `POST /agents/{id}/request-human-intervention`
- [ ] `GET /agents/{id}/context`

#### Sektion 3: Tasks / Assignments / Queue
- [ ] `POST /tasks/{id}/reassign`
- [ ] `POST /tasks/{id}/pause`
- [ ] `POST /tasks/{id}/cancel`
- [ ] `POST /tasks/{id}/retry`
- [ ] `POST /tasks/{id}/force-retry`
- [ ] `POST /tasks/{id}/escalate`
- [ ] `POST /tasks/{id}/replay`

#### Sektion 4: Brain / Knowledge / Epistemics
- [ ] `POST /brain/observations`
- [ ] `POST /brain/claims`
- [ ] `POST /brain/evidence`
- [ ] `POST /brain/verifications`
- [ ] `POST /brain/disputes`
- [ ] `POST /brain/confirmations`
- [ ] `POST /brain/supersede`
- [ ] `POST /brain/escalate`

#### Sektion 5: Council / Verification / Authority
- [ ] `POST /council/verifications`
- [ ] `POST /council/councils`
- [ ] `POST /council/councils/{id}/continue`
- [ ] `POST /council/disputes/{id}/resolve`
- [ ] `POST /council/councils/{id}/escalate`
- [ ] `POST /council/councils/{id}/pivot`
- [ ] `POST /council/councils/{id}/halt`

#### Sektion 6: Execution / Workers / Infrastructure
- [ ] `POST /workers/{id}/drain`
- [ ] `POST /workers/{id}/restart`
- [ ] `POST /workers/{id}/cancel`
- [ ] `POST /swarm/emergency-stop`

#### Sektion 7: Monitoring / Audit / System Health
- [ ] `GET /events/export`
- [ ] `POST /events/clear`
- [ ] `GET /swarm/ops/metrics/export`

---

## 🎯 Parameter Specifikation (Maskinlæsbar)

Hver parameter skal have følgende struktur:

```yaml
parameter:
  name: "agent_name"
  type: "string"
  nullable: false
  default: ""
  allowed_values: null
  min: null
  max: 128
  read_permission: ["controller", "admin", "agent_manager", "developer"]
  write_permission: ["controller", "admin", "agent_manager"]
  action_permission: ["controller", "admin"]
  api_endpoint: "/api/v1/bot-governance/profiles/{id}"
  http_method: "PATCH"
  realtime_source: "/api/v1/swarm/ops/snapshot"
  validation: "required, max_length=128"
  audit_required: true
  dangerous_operation: false
  confirmation_required: false
```

### Eksempler:

#### Agent Parameter
```yaml
agent_name:
  type: "string"
  nullable: false
  default: ""
  allowed_values: null
  min: 1
  max: 128
  read_permission: ["controller", "admin", "agent_manager", "developer"]
  write_permission: ["controller", "admin", "agent_manager"]
  action_permission: []
  api_endpoint: "/api/v1/bot-governance/profiles/{id}"
  http_method: "PATCH"
  realtime_source: "/api/v1/swarm/ops/snapshot"
  validation: "required, max_length=128, regex=^[a-zA-Z0-9_-]+$"
  audit_required: true
  dangerous_operation: false
  confirmation_required: false
```

#### Task Parameter
```yaml
task_priority:
  type: "enum"
  nullable: false
  default: "medium"
  allowed_values: ["low", "medium", "high", "critical"]
  min: null
  max: null
  read_permission: ["controller", "admin", "project_manager", "task_manager", "developer"]
  write_permission: ["controller", "admin", "project_manager"]
  action_permission: []
  api_endpoint: "/api/v1/tasks/{id}"
  http_method: "PATCH"
  realtime_source: "/api/v1/swarm/ops/snapshot"
  validation: "required, enum"
  audit_required: true
  dangerous_operation: false
  confirmation_required: false
```

#### Dangerous Operation
```yaml
emergency_stop:
  type: "action"
  nullable: false
  default: null
  allowed_values: null
  min: null
  max: null
  read_permission: ["controller", "admin"]
  write_permission: []
  action_permission: ["controller", "admin"]
  api_endpoint: "/api/v1/swarm/emergency-stop"
  http_method: "POST"
  realtime_source: null
  validation: null
  audit_required: true
  dangerous_operation: true
  confirmation_required: true
```

---

## 🧠 BI Logik Struktur

### 3 Separate Logikker

#### 1. **Opstart af Projekt (Udvikling af Kravspec)**

**Formål:** Guide brugeren gennem oprettelse af nyt projekt

**Workflows:**
```
1. Vision & Requirements
   ├── System Name
   ├── Business Goals
   ├── Compliance Profile
   ├── Features
   └── Constraints

2. Technology Stack
   ├── Primary Language
   ├── Framework
   ├── Database
   ├── Architecture Pattern
   └── Auth Strategy

3. Agent Selection
   ├── Required Roles
   ├── Capabilities
   ├── Model Preferences
   └── Budget Constraints

4. Project Creation
   ├── Validate Input
   ├── Create Project
   ├── Create Agents
   └── Initialize Workflow
```

**Parametre:**
- Alle `WRITE` parametre i Sektion 1 (Organisation / Projects)
- Alle `WRITE` parametre i Sektion 2 (Agents / Workforce) relateret til agent oprettelse
- `vision_*` parametre
- `tech_*` parametre
- `compliance_*` parametre

**Authority:**
- Kræver `Controller` eller `Admin` roller
- Alle handlinger skal auditeres

---

#### 2. **Styring af Programmering (Execution Management)**

**Formål:** Monitorere og styre aktive udviklingsopgaver

**Workflows:**
```
1. Task Management
   ├── Create Tasks
   ├── Assign Tasks
   ├── Monitor Progress
   └── Handle Failures

2. Queue Management
   ├── Monitor Queue Depth
   ├── Pause/Resume Queue
   ├── Handle Blocked Tasks
   └── Manage Retries

3. Worker Management
   ├── Monitor Worker Health
   ├── Drain/Restart Workers
   ├── Handle Crashes
   └── Emergency Stop

4. Quality Gates
   ├── Monitor Gate Status
   ├── Review Failures
   ├── Override Gates (HITL)
   └── Approve/Reject
```

**Parametre:**
- Alle `READ` og `ACTION` parametre i Sektion 3 (Tasks / Assignments / Queue)
- Alle `READ` og `ACTION` parametre i Sektion 6 (Execution / Workers / Infrastructure)
- Alle `READ` og `WRITE` parametre i Sektion 5 (Council / Verification / Authority) relateret til quality gates

**Authority:**
- `Controller`: Alle handlinger
- `Admin`: Alle handlinger
- `Project Manager`: Task og queue management
- `Task Manager`: Task-specifikke handlinger
- `Operations`: Worker og infrastructure handlinger

---

#### 3. **Administration af Systemet (System Governance)**

**Formål:** Konfigurere og administrere hele systemet

**Workflows:**
```
1. System Configuration
   ├── Redmine Integration
   ├── GitHub Integration
   ├── Security Settings
   └── Monitoring Settings

2. Agent Governance
   ├── Create/Modify Agents
   ├── Manage Capabilities
   ├── Configure Policies
   └── Set Budget Limits

3. Council & Authority
   ├── Configure Council Templates
   ├── Set Verification Policies
   ├── Manage Authority Grants
   └── Configure Escalation Paths

4. System Monitoring
   ├── View System Health
   ├── Monitor Performance
   ├── Review Audit Logs
   └── Export Metrics

5. User Management
   ├── Create Users
   ├── Assign Roles
   ├── Set Permissions
   └── Manage Sessions
```

**Parametre:**
- Alle `WRITE` parametre i alle sektioner
- Alle `ACTION` parametre med `dangerous_operation: true`
- Alle system-konfiguration parametre
- Alle authority og permission parametre

**Authority:**
- `Controller`: Alle handlinger
- `Admin`: Alle handlinger
- `System Admin`: System-specifikke handlinger

---

## 📊 BI Logik Implementation

### Data Model

```python
class BIContext:
    """Business Intelligence Context for GUI"""
    
    # Current state
    current_section: str  # 1-7
    current_view: str  # monitor, edit, actions
    current_resource: str  # project_id, agent_id, task_id, etc.
    
    # User context
    user_id: str
    user_roles: List[str]
    organization_id: str
    project_id: Optional[str]
    
    # Permissions
    read_permissions: List[str]
    write_permissions: List[str]
    action_permissions: List[str]
    
    # Workflow state
    workflow_step: int
    workflow_completed: bool
    workflow_errors: List[str]

class BIWorkflow:
    """Business Intelligence Workflow"""
    
    def __init__(self, workflow_type: str):
        self.type = workflow_type  # opstart, programmering, administration
        self.steps: List[BIWorkflowStep] = []
        self.current_step: int = 0
        self.context: BIContext = BIContext()
    
    def can_proceed(self) -> bool:
        """Check if current step is complete"""
        current = self.steps[self.current_step]
        return current.is_complete()
    
    def get_available_actions(self) -> List[BIAction]:
        """Get actions available for current user in current context"""
        actions = []
        for action in self.steps[self.current_step].available_actions:
            if self._user_can_execute(action):
                actions.append(action)
        return actions
    
    def _user_can_execute(self, action: BIAction) -> bool:
        """Check if user has permission to execute action"""
        return (action.name in self.context.action_permissions or
                action.name in self.context.write_permissions)

class BIAction:
    """Business Intelligence Action"""
    
    def __init__(self, 
                 name: str, 
                 display_name: str,
                 description: str,
                 endpoint: str,
                 method: str,
                 dangerous: bool = False,
                 confirmation_required: bool = False,
                 validation: Optional[Callable] = None):
        self.name = name
        self.display_name = display_name
        self.description = description
        self.endpoint = endpoint
        self.method = method
        self.dangerous = dangerous
        self.confirmation_required = confirmation_required
        self.validation = validation
```

### Workflow Definitions

```python
# Opstart Workflow
OPSTART_WORKFLOW = BIWorkflow("opstart")
OPSTART_WORKFLOW.steps = [
    BIWorkflowStep(
        name="vision",
        display_name="Vision & Requirements",
        required_parameters=["system_name", "business_goals", "features"],
        available_actions=[
            BIAction("save_vision", "Gem Vision", "Gem vision og krav", 
                   "/api/v1/control-plane/projects", "POST", 
                   dangerous=False, confirmation_required=False),
            BIAction("next", "Næste", "Gå til næste step", 
                   null, null, 
                   dangerous=False, confirmation_required=False)
        ]
    ),
    BIWorkflowStep(
        name="technology",
        display_name="Technology Stack",
        required_parameters=["primary_language", "framework", "database"],
        available_actions=[...]
    ),
    # ... flere steps
]

# Programmering Workflow
PROGRAMMERING_WORKFLOW = BIWorkflow("programmering")
PROGRAMMERING_WORKFLOW.steps = [
    BIWorkflowStep(
        name="task_monitor",
        display_name="Task Monitoring",
        required_parameters=[],
        available_actions=[
            BIAction("view_tasks", "Vis Tasks", "Vis alle tasks", 
                   "/api/v1/tasks", "GET", 
                   dangerous=False, confirmation_required=False),
            BIAction("assign_task", "Tildel Task", "Tildel task til agent", 
                   "/api/v1/tasks/{id}/assign", "POST", 
                   dangerous=True, confirmation_required=True),
            # ... flere actions
        ]
    ),
    # ... flere steps
]

# Administration Workflow
ADMINISTRATION_WORKFLOW = BIWorkflow("administration")
ADMINISTRATION_WORKFLOW.steps = [
    BIWorkflowStep(
        name="system_config",
        display_name="System Configuration",
        required_parameters=[],
        available_actions=[
            BIAction("configure_redmine", "Konfigurer Redmine", "Opsæt Redmine integration", 
                   "/api/v1/config/redmine", "POST", 
                   dangerous=False, confirmation_required=False),
            BIAction("emergency_stop", "Nødstop", "Stop hele systemet", 
                   "/api/v1/swarm/emergency-stop", "POST", 
                   dangerous=True, confirmation_required=True),
            # ... flere actions
        ]
    ),
    # ... flere steps
]
```

---

## 🎯 Næste Skridt

### Trin 1: Valider Eksisterende Endpoints ✅ (Færdig)
- [x] Kortlæg alle eksisterende API endpoints
- [x] Kortlæg alle domain models
- [x] Kortlæg alle Pydantic schemas
- [x] Kortlæg alle Streamlit sektioner

### Trin 2: Identificer Mangler ⚠️ (Igang)
- [x] Identificer manglende endpoints for GUI integration
- [ ] Prioriter manglende endpoints
- [ ] Estimer implementeringsomfang

### Trin 3: Implementer Manglende Endpoints
- [ ] Implementer kritiske endpoints (dangerous operations)
- [ ] Implementer monitoring endpoints
- [ ] Implementer audit endpoints

### Trin 4: Opret GUI Control Matrix Database
- [ ] Opret YAML/JSON filer med alle parametre
- [ ] Valider alle parametre mod eksisterende code
- [ ] Generer maskinlæsbar kontrakt

### Trin 5: Implementer GUI Integration
- [ ] Opret API clients for alle endpoints
- [ ] Implementer READ/WRITE/ACTION handling
- [ ] Implementer real-time updates
- [ ] Implementer error handling

### Trin 6: Implementer BI Logik
- [ ] Implementer 3 workflow typer
- [ ] Implementer permission checking
- [ ] Implementer validation
- [ ] Implementer audit logging

### Trin 7: Test & Validering
- [ ] Unit tests for alle endpoints
- [ ] Integration tests for GUI
- [ ] End-to-end tests for workflows
- [ ] Performance tests

---

## 📌 Sammenfatning

| Sektion | READ | WRITE | ACTION | LIVE | ADMIN | AUDIT | Status |
|---------|------|-------|--------|------|-------|-------|--------|
| Organisation / Projects | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Agents / Workforce | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Tasks / Assignments / Queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Brain / Knowledge | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Council / Verification | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Execution / Workers | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |
| Monitoring / Audit | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Færdig |

**Total Parametre:** 200+ 
**Total Endpoints:** 50+ (20+ mangler)
**Total Metrics:** 50+ 
**Total Audit Events:** 50+ 

---

*Dokument oprettet: 2024*
*Version: 2.0*
*Status: Under udvikling*
