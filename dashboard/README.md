# 🎛️ DOR Controller GUI — Decision Cockpit

Interaktiv Control Plane GUI (Streamlit) der gør det menneskelige team til **Controllers**.

## Funktioner

| Sektion | Beskrivelse |
|---------|-------------|
| **Multi-bot Control Plane** | Live, tenant-scoped administration af provider-forbindelser, deployments, botprofiler, council-roller/templates, allokeringspools og frozen selections |
| **System Generator & Workflow** | End-to-end wizard: Krav → AI-råd → HITL-arkitektur → WBS → Kode/verifikation (`workflow_cockpit.py`) |
| **Project & Workspace Overview** | Projekter, fremdrift i %, aktive faser og task-grafer |
| **Decision Cockpit** | Udestående `HUMAN_REQUIRED`-beslutninger med alternativer, risikoscore, AI-rådets stemmer og 1-klik handlinger |
| **Agent Council Feed** | Gennemsigtig bot-dialog (Arkitekt · Security · PM · Impl) |
| **Why? Traceability Inspector** | Årsagskæde: Krav → ADR → Task → Patch → Test |
| **Admin (legacy)** | Opret/se AI-medarbejdere (katalog — ingen runtime-authority) |

## Datakilder

- **Mock fixtures** (`dashboard/fixtures.py`) — kun de ældre demo-cockpits
- **Live API** — Multi-bot Control Plane kræver `DOR_API_BASE`, `DOR_API_TOKEN` og `DOR_ORG_ID` og fejler lukket; mutationer falder aldrig tilbage til mock-data

## Quickstart

1. Installer afhængigheder (fra repo-rod):

   ```bash
   pip install -r requirements.txt
   # eller minimum:
   pip install streamlit pandas cryptography
   ```

2. Sæt obligatoriske secrets:

   ```bash
   export DOR_ADMIN_PASSWORD='replace-with-a-strong-password'
   export DOR_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
   ```

3. (Valgfrit) Live API:

   ```bash
   export DOR_API_BASE=http://localhost:8000
   export DOR_API_TOKEN='...'
   export DOR_ORG_ID=org-eira-demo
   ```

4. Start dashboardet:

   ```bash
   streamlit run dashboard/app.py
   ```

Åbn den viste URL (typisk http://localhost:8501), log ind med `DOR_ADMIN_PASSWORD`, og brug sidebaren til at skifte mellem sektioner og datakilde (Mock / Live).

## Decision Cockpit — handlinger

For hver `HUMAN_REQUIRED`-beslutning:

| Knap | Effekt (session) |
|------|------------------|
| **Godkend anbefaling (A)** | Registrerer `APPROVE_RECOMMENDATION` |
| **Vælg alternativ (B/C)** | Registrerer `CHOOSE_ALTERNATIVE` |
| **Kræv mere undersøgelse** | Registrerer `REQUEST_MORE_INVESTIGATION` |
| **Eget valg** | Registrerer `CUSTOM_CHOICE` med fri tekst |

I denne fase lagres beslutninger i `st.session_state` (demo). Production binder dem til Control Plane command API under authority + audit.

## Filer

```
dashboard/
  app.py               # Hoved-GUI (Controller Cockpit)
  workflow_cockpit.py  # System Generator wizard (5 trin)
  fixtures.py          # Mock projekter, beslutninger, council, traces
  catalog.py           # Præsentationskatalog (roller/capabilities — ingen authority)
  security.py          # Fail-closed admin password + Fernet secrets
  README.md
```

## Sikkerhed

- Dashboard kræver `DOR_ADMIN_PASSWORD` (fail-closed).
- API-nøgler i legacy-admin krypteres med `DOR_ENCRYPTION_KEY` (Fernet).
- Mock-data giver **ingen** runtime-authority; live-kald kræver gyldig token og org-scope.
- Multi-bot-siden sender aldrig provider-secrets. Forbindelser oprettes med en `secret_reference`, som serveren resolver gennem den godkendte secret-backend.
- Roller vælges af Controlleren og bindes til pools af versionerede botprofiler. Systemet vælger kun inden for disse pools; der findes ingen hardcoded brand→rolle-binding.
