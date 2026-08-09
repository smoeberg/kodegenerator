# 📚 Digital Organization Runtime (DOR) - Dokumentation

**Version:** 1.0.0  
**Senest opdateret:** 3. august 2026  

---

## 📌 Indholdsfortegnelse

1. [📖 Introduktion](#-introduktion)
2. [🏗️ Arkitektur](#%EF%B8%8F-arkitektur)
3. [📦 Domæneobjekter](#-dom%C3%A6neobjekter)
4. [🔧 Implementering](#-implementering)
5. [🌐 API (FastAPI)](#-api-fastapi)
6. [🤖 AI Integration](#-ai-integration)
7. [⚙️ Task Executors](#%EF%B8%8F-task-executors)
8. [📊 Monitoring & Observability](#-monitoring--observability)
9. [🚀 Deployment](#-deployment)
10. [📝 Eksempler](#-eksempler)
11. [🔍 Fejlfinding](#-fejlfinding)
12. [📜 Changelog](#-changelog)
13. [🤝 Bidrag](#-bidrag)
14. [📄 Licens](#-licens)

---

## 📖 Introduktion

### Hvad er DOR?
**Digital Organization Runtime (DOR)** er et operativsystem for digitale organisationer, der gør det muligt at:
* Organisere AI-medarbejdere, roller og afdelinger som en traditionel virksomhed.
* Styre workflows, tasks og artefakter med versionering, godkendelser og historik.
* Integrere med LLM'er (GPT-5, Claude-3, Mistral, etc.) for at automatisere opgaver som kodegenerering, code review og dokumentation.
* Overvåge og spore alle handlinger med logging, metrics og tracing.

DOR er ikke et traditionelt multi-agent system. Det er en digital virksomhed, hvor:
* **Roller** (f.eks. *Senior Python Developer*) er permanente.
* **Medarbejdere** (f.eks. *GPT-5*) er udskiftelige.
* **Artefakter** (f.eks. *Implementation Package*) er versionerede og sporbare.
* **Workflows** er deterministiske og auditerbare.

### 🎯 Formål
DOR er designet til at:
* ✅ Strukturere AI-arbejde som en traditionel organisation.
* ✅ Automatisere softwareudvikling (og senere andre domæner som salg, marketing, etc.).
* ✅ Sikre kvalitet via governance, reviews og policies.
* ✅ Gøre systemet auditabelt med fuld historik og sporbarhed.
* ✅ Skalere horisontalt med Kubernetes, load balancing og distributed tracing.

### 🔗 Relaterede Projekter
* **EIRA Engineering Office (EEO)** – Referenceimplementering af DOR for softwareudvikling.
* **LangGraph** – Workflow-orchestration for LLM'er (bruges som inspiration).
* **FastAPI** – API-framework brugt i DOR.

---

## 🏗️ Arkitektur

### 📊 Overordnet Arkitektur
DOR følger en lagdelt arkitektur med klare adskillelser mellem:
1. **Domain Layer** (Kernedomæner: Organization, Actor, Workflow, etc.).
2. **Application Layer** (Use Cases: IntentResolver, WorkflowEngine, etc.).
3. **Infrastructure Layer** (Eksterne services: Database, LLM Providers, GitHub, etc.).
4. **Interface Layer** (API, CLI, Webhooks).

### 🏢 Organisationsstruktur
DOR organiserer digitale medarbejdere i en hierarkisk struktur med afdelinger, roller, capabilities og governance.

### 🔄 Workflow Lifecycle
Hvert Workflow følger en tilstandsmaskine med klare overgange, gates og godkendelsestrin.

### 📦 Artefakt Hierarki
Alle Artefakter er versionerede med SHA-256 hash og kan referere til hinanden i forældre/barn-strukturer.

### 🔒 Sikkerhedsarkitektur
DOR bruger:
* JWT-autentificering for API-adgang.
* Role-Based Access Control (RBAC) for at styre tilladelser for hver rolle.
* Policy Engine for at håndhæve regler (f.eks. "Ingen direkte commits til main").
* Audit Logs for at spore alle handlinger.

---

## 📦 Domæneobjekter

### 📌 Core Domain Objects (8 stk.)

| Objekt | Beskrivelse | Eksempel |
| :--- | :--- | :--- |
| **Organization** | Juridisk/operationel identitet. | EIRA, Acme Corp |
| **Actor** | Enhed (AI, menneske, service). | GPT-5, John Doe, GitHub Bot |
| **RoleDefinition** | Stillingens definition. | Senior Python Developer |
| **Capability** | Evne, som en Actor kan have. | `python.fastapi.expert` |
| **Intent** | Mål/ønsket resultat. | Implement OAuth2 |
| **Workflow** | Procesdefinition. | Feature Development Workflow |
| **Task** | Opgave i et workflow. | Implementér OAuth2 endpoints |
| **Artifact** | Verificerbart resultat. | ArchitectureDecision v1.0.0 |
| **Event** | Hændelse (audit, læring). | `ARTIFACT_APPROVED` |

---

## 🔧 Implementering

### 🚀 Setup og Installation

1. **Klon Repository:**
   ```bash
   git clone https://github.com/smoeberg/kodegenerator.git
   cd kodegenerator
   ```

2. **Opret Virtual Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # På Windows: venv\Scripts\activate
   ```

3. **Installér Afhængigheder:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Konfigurer Miljøvariabler:**
   Opret en `.env`-fil i roden af projektet:
   ```env
   DATABASE_URL=sqlite:///./dor_runtime.db
   DOR_JWT_SECRET_KEY=replace-with-a-long-random-secret
   DOR_ADMIN_PASSWORD=replace-with-a-dashboard-password
   DOR_ENCRYPTION_KEY=replace-with-a-generated-fernet-key
   OPENAI_API_KEY=your-openai-key
   ANTHROPIC_API_KEY=your-anthropic-key
   ```

---

## 🌐 API (FastAPI)

DOR leverer et RESTful API bygget med FastAPI til administration af organisationer, actors, roller, intents, workflows, tasks og artefakter.

---

## 🤖 AI Integration

DOR understøtter integration med ledende LLM'er:

| Model | Udbyder | Capabilities | Max Tokens |
| :--- | :--- | :--- | :--- |
| **GPT-5** | OpenAI | Python, JavaScript, Code Review | 100,000 |
| **Claude 3** | Anthropic | Python, Rust, Code Review | 100,000 |
| **DeepSeek Coder** | DeepSeek | Python, C++, Java | 32,000 |
| **Mistral Large** | Mistral | Python, JavaScript, French | 32,000 |
| **Gemini 1.5 Pro** | Google | Python, Multi-Modal | 1,000,000 |

---

## ⚙️ Task Executors

DOR benytter en `TaskExecutorFactory` til at dirigere tasks til den korrekte executor ud fra Actor-typen:

* **DIGITAL_EMPLOYEE** $\rightarrow$ `AITaskExecutor` (LLM-kald til kodegenerering, reviews, m.m.)
* **HUMAN** $\rightarrow$ `HumanTaskExecutor` (Notifikationer og godkendelsesflows)
* **SERVICE** $\rightarrow$ `ServiceTaskExecutor` (Integration til GitHub, Jira, Slack osv.)

---

## 📊 Monitoring & Observability

* **Logging:** Struktureret JSON-logging via `structlog`.
* **Metrics:** Performance tracking og udnyttelse via `prometheus-client`.
* **Tracing:** Distributed tracing på tværs af services via `OpenTelemetry`.

---

## 📜 Changelog

* **1.0.0** (2026-08-03) – Initial release af Digital Organization Runtime (DOR) specifikation og arkitektur.

---

## 📄 Licens

DOR er licenseret under **MIT License**. Se [LICENSE](LICENSE) for detaljer.
