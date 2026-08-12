# 📚 Digital Organization Runtime (DOR) - Dokumentation

**Version:** 1.1.0  
**Senest opdateret:** 12. august 2026  

---

## 📌 Canonical architecture

The current Phase 4 target is **EIRA Brain & Workforce Control Plane**. The canonical specification is:

- [Phase 4 — EIRA Brain & Workforce Control Plane](docs/PHASE4_ARCHITECTURE.md)

This specification supersedes earlier Phase 4 concepts based on a generic conversation engine. Those concepts are historical and are not the implementation target.

### Phase 4 in one view

```text
LibreChat
   │
   │ Interactive
   ▼
EIRA Control Plane
   ├── Agent Registry
   ├── Assignment
   ├── Brain
   └── Verification Policy
           │
           ▼
      Phase 7 Queue
           │
           ▼
         Worker
           │
           ▼
      Agent Runtime
```

The fundamental invariants are:

- **Agent ≠ Assignment ≠ Worker**
- **Context ≠ Knowledge**
- **Knowledge confirmation ≠ execution authority**
- **LibreChat ≠ autonomous worker runtime**
- **Phase 7 owns durable work execution and worker leases**
- **Phase 1–3 authority controls remain the execution authorization boundary**

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
* **Brain** vedligeholder organisationens epistemiske viden separat fra den kortvarige task context.

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

Phase 4 er EIRA's **Brain & Workforce Control Plane**. LibreChat er et interaction surface for menneskelig interaktion; det er ikke systemets authoritative agent registry, Brain eller autonomous worker runtime.

Phase 7 leverer durable queueing, worker leases, retries og recovery. Phase 6 er den sikre execution boundary. Phase 5 håndterer work-product/release lifecycle. Phase 1–3 ejer governance og authority.

Se den [kanoniske Phase 4-specifikation](docs/PHASE4_ARCHITECTURE.md) for invariants, execution modes, Brain-model, verification, concurrency, failure recovery og LibreChat boundary.

---

## 📦 Domæneobjekter

| Objekt | Beskrivelse |
| :--- | :--- |
| **Organization** | Juridisk/operationel identitet. |
| **Actor** | Enhed (AI, menneske, service). |
| **RoleDefinition** | Stillingens definition. |
| **Capability** | Evne, som en Actor/Agent kan have. |
| **Agent** | Persistent digital medarbejderidentitet. |
| **Assignment** | Binding af arbejde til en Agent. |
| **ContextPacket** | Afgrænset task-context; ikke organisatorisk knowledge. |
| **KnowledgeRecord** | Epistemisk record: observation, claim, evidence eller verification. |
| **KnowledgeState** | Materialiseret aktuel knowledge state. |
| **VerificationPolicy** | Regler for deterministisk verification, single-agent, quorum eller human escalation. |
| **Task** | Opgave i et workflow. |
| **Artifact** | Verificerbart, versioneret resultat. |
| **Event** | Hændelse til audit, læring og sporbarhed. |

---

## 🔒 Sikkerheds- og authority boundary

Brain kan etablere eller bekræfte viden, men **CONFIRMED knowledge er aldrig i sig selv execution authority**.

Execution følger fortsat:

```text
AuthorityDecision
      ↓
VerifiedAuthorityGrant
      ↓
Phase 6 execution boundary
```

Dette er en fast arkitekturinvariant.

---

## 🤖 AI og agent execution

Systemet har to execution modes:

### Interactive

```text
Human → LibreChat → Agent → EIRA Control Plane
```

### Autonomous

```text
Trigger → Assignment → Phase 7 Queue → Worker → Agent
```

Autonome workers kalder model providers og tools direkte via EIRA execution path. LibreChat bruges ikke som worker loop.

---

## ⚙️ Task Executors

DOR kan dirigere tasks til passende executors ud fra Actor-/agent-typen. Den konkrete execution skal fortsat passere de eksisterende governance, work-product og sandbox boundaries.

---

## 📊 Monitoring & Observability

* **Logging:** Struktureret logging.
* **Metrics:** Performance og resource tracking.
* **Tracing:** Distributed tracing på tværs af services.
* **Audit:** Agent-, assignment-, epistemic- og execution-hændelser skal kunne spores.

---

## 📜 Changelog

* **1.1.0** (2026-08-12) – Phase 4 redefined as EIRA Brain & Workforce Control Plane; LibreChat established as interaction surface; Agent/Assignment/Worker, epistemic knowledge and verification boundaries documented.
* **1.0.0** (2026-08-03) – Initial DOR specification and architecture.

---

## 📄 Licens

DOR er licenseret under **MIT License**. Se [LICENSE](LICENSE) for detaljer.
