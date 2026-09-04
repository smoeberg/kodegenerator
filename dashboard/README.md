# DOR Control Plane GUI

`dashboard/app.py` er den kanoniske Streamlit-GUI for Digital Organization Runtime.
GUI'en er en tynd, authenticated klient til `api/main.py`: domæneregler,
authority, tenant-scope og state transitions ligger i backend.

## Én kanonisk surface

Start GUI'en fra repo-roden:

```bash
streamlit run dashboard/app.py
```

GUI'en bruger kun `dashboard.api_client.DORAPIClient` som HTTP-transport. Login
henter et bearer-token fra backend, og samme token/base URL bruges på tværs af
projekt-, execution-, governance- og integrationsviews.

Der er ingen mock fallback og ingen separat dashboard-tokenkonfiguration.
Hvis backend ikke kan verificere en handling eller integration, viser GUI'en
ikke en lokal successtatus.

## De tre top-level logikker

### 1. Projekt & Krav

- opret tenant-scoped projekter/intents gennem Control Plane API
- hent eksisterende projektstatus
- request launch med eksplicit command ID og expected fingerprint
- læs projekt-events

### 2. Udvikling & Decision Cockpit

- live execution-status og realtime events
- task/fase-overblik
- fail-closed manual advance
- Quality Gates med `approved` / `rejected` beslutninger gennem Execution API
- implementation proposals og diffs
- read-only Why / Evidence Trace

Backend er eneste authority for workflow-progression og gate-state. En rejected
gate forbliver blocking, indtil backend tilbyder en eksplicit rework/retry-
transition.

### 3. Administration & Governance

Bot Governance-fanen er den integrerede Multi-bot Control Plane og bruger samme
authenticated `DORAPIClient` som resten af GUI'en. Den understøtter:

- provider-forbindelser
- deployments
- botprofiler
- roller
- council templates
- allokeringspools
- frozen bot selections
- read-only durable bot-evidence

Alle kald scopes med den valgte `organization_id`. Governance er append-only;
deaktivering sker kun gennem eksplicitte backend-commands.

Administration indeholder også:

- **Redmine Integration** — server-side, fail-closed health verification via
  `GET /api/v1/integrations/redmine/health`
- **System Health** — backend readiness/drift

Redmine API-key håndteres kun af API-processen og sendes aldrig til Streamlit-
klienten.

## Konfiguration

Dashboard-transport:

```bash
export DOR_API_URL=http://localhost:8000
```

Default i container-topologien er `http://api:8000`.

Brugercredentials valideres af backend via `/auth/token`; GUI'en gemmer kun det
returnerede access token i Streamlit session-state.

Redmine konfigureres server-side på API-servicen:

```bash
export REDMINE_URL=https://redmine.example.com
export REDMINE_API_KEY=...
export REDMINE_PROJECT_ID=my-project
```

## Centrale filer

```text
dashboard/
  app.py                       # eneste top-level Streamlit entrypoint
  api_client.py                # eneste dashboard HTTP-transport
  state.py                     # authenticated session-state
  realtime.py                  # workflow realtime transport
  cockpit_view_model.py        # execution/gate/evidence normalization
  evidence_trace.py            # read-only Why / Evidence Trace
  multi_bot_control_plane.py   # live tenant-scoped bot governance UI
  governance_catalog.py        # API paths + schema-validerede eksempelpayloads
  integration_view_model.py    # integrationsstatus normalization
  redmine_integration.py       # fail-closed Redmine status UI
```

## Retired demo/legacy surfaces

Følgende gamle dashboard-paths er bevidst fjernet og må ikke genindføres som
parallelle production-surfaces:

- `dashboard/decision_cockpit.py` — hardcodede beslutninger/lokale success states
- `dashboard/swarm_monitor.py` — random session-state mock fleet
- `dashboard/workflow_cockpit.py` — mock wizard/council/WBS/test evidence
- `dashboard/fixtures.py` — demo-data
- `dashboard/index.html` — statiske ONLINE/READY/ENFORCING badges
- `dashboard/control_plane_api.py` — parallel HTTP-klient/token-flow
- `dashboard/catalog.py` — legacy presentation-only role catalog
- `dashboard/security.py` — legacy lokal password/secret-store

`tests/dashboard/test_dashboard_surface.py` låser denne boundary.

## Sikkerheds- og authority-principper

- GUI'en opfinder aldrig backend-success.
- Secrets lagres ikke i browser/Streamlit-inputs.
- Tenant-scope sendes eksplicit til governance-kald.
- Gate-decisions og workflow-advance afgøres af backend.
- Evidence views er read-only og må ikke fabricere direkte provenance-links,
  som backend ikke eksponerer.
- Der findes én production GUI entrypoint og én dashboard HTTP-klient.
