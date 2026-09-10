# DOR GUI surfaces

DOR bruger én intern Operator GUI over den authoritative FastAPI-backend.
GUI-laget er en tynd authenticated klient: domæneregler, authority, tenant-scope,
secrets og state transitions ligger i backend.

## GUI-01 — Operator + Administration

`dashboard/operator_center.py` er den canonical interne DOR-applikation.

Start fra repo-roden:

```bash
streamlit run dashboard/operator_center.py --server.port 8501
```

Den samme deployment indeholder to capabilities:

```text
DOR Operator GUI :8501
│
├── Case Journey
│   ├── Sag
│   ├── Plan
│   ├── Aktivt arbejdsgrundlag
│   ├── Execution
│   ├── Proposal
│   └── Beslutning
│
└── Administration
    ├── Organisationer
    ├── Brugere
    ├── Projekter
    ├── Redmine
    ├── Implementation AI
    └── System configuration / health
```

Administration vises kun, når det aktuelle backend organization catalog eksplicit
bekræfter `is_admin=true` for den aktive organisation. `false` skjuler
administrations-capability'en. Manglende, ukendt eller malformed administratorstatus
failer closed med `Status kan ikke fastslås` og giver ingen administrativ navigation.

Denne UI-gating er kun presentation. Hver administrativ API-operation bliver fortsat
autentificeret, autoriseret og organization-scoped i FastAPI-backenden.

### Administrative capabilities

De aktuelle backend-kontrakter understøtter:

- **Organisationer** — list, create og update.
- **Brugere** — list, create og update, herunder den eksisterende organization
  `is_admin`-markering og aktivering/deaktivering.
- **Projekter** — read-only katalog for den aktive organisation. Project lifecycle,
  Cases og execution forbliver i Operator/Case Journey.
- **Redmine** — URL, external project ID, krypteret API-key og connection test.
  Et tomt replacement-secret sendes ikke, så den gemte secret bevares.
- **Implementation AI** — model, base URL, krypteret API-key og connection test.
- **System** — API liveness og database/readiness. Uventede eller malformed
  responses vises som `Status kan ikke fastslås`, aldrig som success.

### Kendte backend-gaps

Administration fabrikerer ikke funktionalitet for capabilities uden canonical
administrativ backend-kontrakt. Det gælder fortsat bl.a.:

- generisk RBAC/permission administration ud over organization `is_admin`
- departments
- project membership
- repository mappings
- GitHub/GitLab administrative mappings
- notification configuration
- mutable MFA/SSO/session/security policy
- global administrativ audit query/log

Disse hører til senere ADM-02/INT-02/operations-slices.

## GUI-02 — Customer Portal

GUI-02 er reserveret til den eksterne/customer-facing portal på port `8502`.
GUI-02 ændres ikke af administrationens integration i GUI-01.

```text
GUI-01  Operator + Administration  :8501
GUI-02  Customer Portal            :8502
```

Der findes ingen GUI-03 deployment på `8503`.

## Retired standalone GUI-03

Den tidligere standalone entrypoint `dashboard/admin_app.py` er fjernet.
GUI-03-navnet beskriver herefter kun den administrative capability, som er
integreret i GUI-01. Der er ingen separat admin-container, healthcheck, port
eller deployment.

`dashboard/admin_api.py` kan fortsat bruges som en transport-only facade i tests
og hjælpefunktioner, men den er ikke en application entrypoint og ejer ingen
session-, authorization- eller configuration-state.

## Shared transport og login

Operator og Administration genbruger:

```text
dashboard/api_client.py
dashboard/state.py
dashboard/context_navigation.py
```

Dashboard-transport konfigureres med:

```bash
export DOR_API_URL=http://localhost:8000
```

I container-topologien kalder Operator GUI backenden via `http://api:8000`.

Brugercredentials valideres af backend via `/auth/token`. Browseren gemmer kun
det returnerede access token i Streamlit session state. Integration secrets
sendes kun ved eksplicit mutation; eksisterende secrets returneres aldrig til
GUI'en i plaintext.

## Security- og authority-principper

- GUI'en opfinder aldrig backend-success.
- Backend håndhæver authentication, authorization og organization isolation.
- Skjult admin-navigation er ikke en security boundary.
- Ukendt administratorstatus failer closed.
- Ukendt/malformed health eller configuration state bliver ikke success.
- Secrets vises aldrig igen efter lagring og gemmes ikke som GUI-owned config.
- Administration har ingen deployment-, release-, workflow execution-, PR-
  creation- eller Patch Apply-path.
- Administrative mutationer går kun gennem canonical FastAPI endpoints.
- Case Journey forbliver DOR-authoritative og uændret.

## Deployment

`compose.yml` har én intern dashboard-service. Den starter:

```text
dashboard/operator_center.py
port 8501
```

Administration kører i samme Streamlit-proces og kræver ingen ekstra service.
