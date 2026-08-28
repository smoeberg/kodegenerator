# 📚 Digital Organization Runtime (DOR) - Dokumentation

**Version:** 1.3.0

**Senest opdateret:** 27. august 2026

---

## 📌 Canonical architecture

The current Phase 4 target is **EIRA Brain & Workforce Control Plane**. The canonical specification is:

- [Phase 4 — EIRA Brain & Workforce Control Plane](docs/PHASE4_ARCHITECTURE.md)

This specification supersedes earlier Phase 4 concepts based on a generic conversation engine. Those concepts are historical and are not the implementation target.

### Phase 4 in one view (aligned with the repository)

```text
LibreChat / HTTP API (auth)
   │  Interactive surface — not the worker runtime
   ▼
EIRA Control Plane  (package: phase4/)
   ├── AI-1 Agent registry          phase4/agent_registry
   ├── AI-2 Context packets         phase4/context_packet
   ├── AI-3 Authority               phase4/authority  (HMAC VerifiedAuthorityGrant)
   ├── AI-4 Execution               phase4/execution  (grant-only + replay ledger)
   ├── Epistemic persistence        phase4/brain_persistence
   ├── Dialectical Council          phase4/council  (durable rounds + readiness)
   ├── Belief revision              phase4/epistemics
   ├── Anti-Tube adaptation         phase4/adaptation
   ├── Implementation agent         phase4/implementation_agent
   ├── Project audit                phase4/project_audit
   └── Verification / planner / …   phase4/verification, planner, …
           │
           ├─ Phase 5 work-product lifecycle    phase5/
           ├─ Phase 6 execution sandbox         phase6/
           └─ Phase 7 durable queue / workers   phase7/ + infrastructure/runtime
```

**Canonical HTTP entrypoint:** `api/main.py` (health, auth, control_plane, workflows, implementation_agent).  
Legacy routers such as `api/endpoints/tasks.py` are **not** mounted and must not be exposed without a tenant-scoped redesign — see [SECURITY.md](SECURITY.md).

The fundamental invariants are:

- **Agent ≠ Assignment ≠ Worker**
- **Context ≠ Knowledge** (`context_packet` vs `brain_persistence` / knowledge contracts)
- **Knowledge confirmation ≠ execution authority** (only `VerifiedAuthorityGrant` executes)
- **LibreChat ≠ autonomous worker runtime**
- **Phase 7 owns durable work execution and worker leases**
- **Phase 1–3 organization authority remains the multi-tenant API boundary**
- **AI-3 → AI-4 is fail-closed** (raw `AuthorityDecision` is not executable)
- **Council readiness ≠ authority** (`DecisionReadiness` must still pass AI-3)
- **Repeated identical failures force pivot** (Anti-Tube prevents blind retry)

### Authority and execution (implemented)

```text
AuthorityEngine.evaluate → AuthorityDecision (+ provenance)
        → VerifiedAuthorityGrant.from_decision (HMAC, TTL ≤ 5 min)
        → ExecutionEngine.execute(request, grant)
        → ExecutionReplayLedger claim (P4-01) → adapter
```

Details: [P4-00D security review](docs/phase4/P4_00D_SECURITY_REVIEW.md), [P4-01 replay ledger](docs/phase4/P4_01_REPLAY_LEDGER.md), [SECURITY.md](SECURITY.md).

---

## 📖 Introduktion

### Hvad er DOR?
**Digital Organization Runtime (DOR)** er et operativsystem for digitale organisationer, der gør det muligt at:
* Organisere AI-medarbejdere, roller og afdelinger som en traditionel virksomhed.
* Styre workflows, tasks og artefakter med versionering, godkendelser og historik.
* Integrere med LLM'er for at automatisere opgaver som kodegenerering, code review og dokumentation.
* Overvåge og spore alle handlinger med logging, metrics og tracing.

DOR er ikke et traditionelt multi-agent system. Det er en digital virksomhed, hvor:
* **Roller** er permanente organisatoriske definitioner.
* **Agenter** er persistente digitale medarbejderidentiteter.
* **Workers** er ephemeral compute og må ikke forveksles med agenter.
* **Artefakter** er versionerede og sporbare.
* **Workflows** er deterministiske og auditerbare.
* **Brain** vedligeholder organisationens epistemiske viden separat fra den kortvarige task context (`phase4/brain_persistence`).

### 🎯 Formål
DOR er designet til at:
* ✅ Strukturere AI-arbejde som en traditionel organisation.
* ✅ Automatisere softwareudvikling og senere andre domæner.
* ✅ Sikre kvalitet via governance, reviews og policies.
* ✅ Gøre systemet auditabelt med fuld historik og sporbarhed.
* ✅ Skalere horisontalt med elastiske workers.

---

## 🏗️ Arkitektur

DOR følger en lagdelt arkitektur med klare adskillelser mellem domain, application, infrastructure og interface.

| Lag / mappe | Ansvar |
|-------------|--------|
| `domain/` | Domæneobjekter og kontrakter |
| `phase4/` | EIRA control plane (authority, execution, agents, brain persistence) |
| `phase5/`–`phase7/` | Work-product, sandbox, durable queue |
| `infrastructure/persistence/` | SQLAlchemy models, org-scoped repositories |
| `api/` | Canonical HTTP surface (`main.py`) |
| `runtime/` | Organization context, command/project runtimes |
| `tests/` | Phase-strukturerede tests (inkl. P4-00D adversarial) |

Yderligere: [docs/PHASE4_ARCHITECTURE.md](docs/PHASE4_ARCHITECTURE.md), [docs/ROADMAP.md](docs/ROADMAP.md).

### Deployment and releases

The software-factory pipeline can build and push generated Docker images and
publish verified patches as governed GitHub pull requests. Configuration,
credential boundaries, payload examples, expected PR format, and troubleshooting
are documented in [Deployment and release operations](docs/DEPLOYMENT_AND_RELEASE.md).

Minimal deployment example:

```python
from execution.pipeline_executors import DeployExecutor

result = DeployExecutor().execute({
    "project_name": "orders-api",
    "environment": "staging",
    "target": "https://orders-staging.example.com",
    "files": [
        {"path": "Dockerfile", "content": "FROM python:3.12-slim\nCOPY . /app\n"},
        {"path": "app.py", "content": "print('ready')\n"},
    ],
})
```

---

## 📜 Changelog

* **1.3.0** (2026-08-27) – Durable dialectical Council runtime, content-addressed orchestrator turns, evidence-derived readiness and Anti-Tube preemption.
* **1.2.0** (2026-08-18) – README aligned to implemented control plane modules; SECURITY.md; P4-01 ledger overview; legacy API warning.
* **1.1.0** (2026-08-12) – Phase 4 redefined as EIRA Brain & Workforce Control Plane; LibreChat established as interaction surface.
* **1.0.0** (2026-08-03) – Initial DOR specification and architecture.
# Governed LLM proposals

Architecture, contract and test stages can optionally request schema-validated,
side-effect-free model proposals. Configuration, payloads, provenance and failure
behaviour are documented in [docs/GOVERNED_LLM.md](docs/GOVERNED_LLM.md).

Durable pipeline snapshots, migrations, worker recovery and cross-worker LLM
replay are documented in
[docs/PIPELINE_PERSISTENCE.md](docs/PIPELINE_PERSISTENCE.md).

Exactly-once coordination for Docker/deployment and pull-request side effects is
documented in
[docs/TERMINAL_SIDE_EFFECTS.md](docs/TERMINAL_SIDE_EFFECTS.md).

The real TCP/Uvicorn pipeline acceptance gate and worker HTTP contract are
documented in [docs/HTTP_ACCEPTANCE.md](docs/HTTP_ACCEPTANCE.md).
