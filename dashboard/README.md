# DOR GUI surfaces

DOR har separate GUI-surfaces over den samme authoritative FastAPI-backend.
GUI-lagene er tynde authenticated klienter: domæneregler, authority, tenant-scope,
secrets og state transitions ligger i backend.

## GUI-01 — Operator / Case Journey

`dashboard/app.py` er den kanoniske interne Operator-GUI.

Start fra repo-roden:

```bash
streamlit run dashboard/app.py --server.port 8501
```

GUI-01 ejer den operative brugerrejse omkring Case, Plan, aktivt arbejdsgrundlag,
Execution, Evidence, Implementation Proposal og Decision status. Backend er eneste
authority for workflow-progression og gate-state.

## GUI-03 — Administration & Configuration

`dashboard/admin_app.py` er den selvstændige administrative surface. Den kan
startes uden GUI-01 og uden Customer Portal GUI-02:

```bash
streamlit run dashboard/admin_app.py --server.port 8503
```

GUI-02 er reserveret til port `8502`; GUI-03 bruger derfor `8503` i lokal
standardkørsel. Porten ligger i startkommandoen og er ikke hardcodet i Python-
koden.

GUI-03 genbruger `dashboard.api_client.DORAPIClient` og det eksisterende
session-state/login-flow. Den opretter ikke en parallel HTTP-klient, tokenmodel,
authority-model eller lokal konfigurationsdatabase.

### Understøttede administrative capabilities

De aktuelle backend-kontrakter giver GUI-03 følgende reelle surfaces:

- **Administration Overview** — API liveness, database readiness, Redmine status
  og et eksplicit capability map.
- **Organisationer** — liste, opret og rediger organisationens navn/beskrivelse.
- **Brugere** — liste, opret, profil/password, aktiv/deaktiv og organization-admin
  via det durable identity store og server-side organization-admin kontrol.
- **Projekter** — read-only administrativ katalogvisning. Lifecycle og Case-arbejde
  forbliver i GUI-01.
- **Redmine** — URL/project config, krypteret API-token via backend og sikker
  forbindelsestest.
- **Implementation AI** — model/base URL/credential config og forbindelsestest.
- **System & Security** — liveness/readiness og eksplicit read-only security status.

### Kendte backend-gaps

GUI-03 fabrikerer ikke funktionalitet for capabilities, der ikke har en
canonical administrativ backend-kontrakt. I den aktuelle API gælder det bl.a.:

- generisk RBAC/permission administration ud over organization `is_admin`
- departments
- project membership/repository mapping
- GitHub/GitLab administrative repository mappings
- notification configuration
- mutable MFA/SSO/session/security policy
- global administrativ audit query/log

Disse gaps vises som `Begrænset`, `Read-only` eller `Ikke understøttet af backend`.
`Status kan ikke fastslås` anvendes, når backend/transport ikke kan etablere en
status. Projekt-events genbruges ikke som falsk global admin-audit.

## Shared transport og login

Begge interne GUI'er bruger kun:

```text
dashboard/api_client.py
```

Dashboard-transport konfigureres med:

```bash
export DOR_API_URL=http://localhost:8000
```

Default i container-topologien er `http://api:8000`.

Brugercredentials valideres af backend via `/auth/token`; GUI'erne gemmer kun det
returnerede access token i Streamlit session-state. Secret input sendes kun ved
den eksplicitte backend-mutation og gemmes ikke som GUI-owned configuration.
Eksisterende integration credentials returneres aldrig til GUI'en; kun
`api_key_configured`/status eksponeres.

## GUI-01 funktioner

Operator-GUI'en indeholder bl.a.:

- tenant-scoped projekt/intents og projektstatus
- canonical Case Journey
- execution-status og realtime events
- Quality Gates og backend-authoritative decisions
- implementation proposals og diffs
- read-only Why / Evidence Trace
- Multi-bot Control Plane

GUI-03 flytter eller kopierer ikke disse operative capabilities.

## Centrale filer

```text
dashboard/
  app.py                       # GUI-01 Operator entrypoint
  admin_app.py                 # GUI-03 Administration entrypoint
  admin_api.py                 # GUI-03 authoritative API facade
  api_client.py                # shared HTTP transport
  state.py                     # shared authenticated session-state
  realtime.py                  # GUI-01 workflow realtime transport
  case_shell_views.py          # GUI-01 canonical Case Journey
  multi_bot_control_plane.py   # GUI-01 bot governance UI
```

## Retired demo/legacy surfaces

Følgende gamle dashboard-paths er fortsat retired og må ikke genindføres som
parallelle production-surfaces:

- `dashboard/decision_cockpit.py`
- `dashboard/swarm_monitor.py`
- `dashboard/workflow_cockpit.py`
- `dashboard/fixtures.py`
- `dashboard/index.html`
- `dashboard/control_plane_api.py`
- `dashboard/catalog.py`
- `dashboard/security.py`
- `dashboard/pages/00_Project_Lifecycle.py`

## Sikkerheds- og authority-principper

- GUI'en opfinder aldrig backend-success.
- Backend håndhæver authorization og organization isolation; skjulte knapper er
  ikke sikkerhed.
- Secrets vises aldrig igen efter lagring og logges ikke af GUI-03.
- Unknown state forbliver unknown og åbner ikke farlige handlinger.
- GUI-03 har ingen direkte deployment-, release-, execution-, PR-creation- eller
  Patch Apply-path.
- Administrative mutationer går kun gennem canonical FastAPI endpoints.
- GUI-01's Case Journey forbliver separat og uændret.

## Test

Fokuserede GUI-03 boundary-tests:

```bash
pytest -q tests/dashboard/test_admin_api.py tests/dashboard/test_admin_surface.py
```

Den eksisterende dashboard-suite køres fortsat for regression:

```bash
pytest -q tests/dashboard
```
