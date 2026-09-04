# GUI Live Control Plane

## Scope

The Streamlit dashboard is a thin client over the canonical FastAPI surface. It
must not recreate domain state in SQLite, invent legacy REST endpoints, or
bypass authorization.

The GUI is organized into three business logics:

1. **Projekt & Krav** — define immutable project intent and request launch of an
   exact fingerprint-bound snapshot.
2. **Udvikling & Eksekvering** — inspect and control workflow/pipeline/gates and
   governed execution decisions.
3. **Systemadministration** — tenant-scoped bot governance: profiles, roles,
   templates, connections, deployments and allocations.

Observability is cross-cutting, not a fourth business logic.

## Authentication

- `POST /auth/token` uses the FastAPI OAuth2 password flow.
- The GUI stores only the returned access token in Streamlit session state.
- Every API request uses `Authorization: Bearer <token>`.
- A `401` clears the GUI session and requires login again.
- Dashboard code never persists the administrator password.

## Project contract

Create:

- `POST /api/v1/control-plane/projects`
- `organization_id`
- `command_id`
- `name`
- `description`
- `intent.goal`
- `intent.description`
- `intent.priority` (`low|medium|high|critical`)
- `intent.constraints` (object)
- `intent.required_capabilities` (unique list)

Read:

- `GET /api/v1/control-plane/projects/{project_id}?organization_id=...`
- `GET /api/v1/control-plane/projects/{project_id}/events?organization_id=...`

Launch is not a generic update. It requires:

- `organization_id`
- `command_id`
- `expected_project_fingerprint`

This prevents the GUI from launching a different project snapshot than the one
that was reviewed.

## Governance contract

All bot-governance reads are explicitly tenant-scoped with
`organization_id`. The GUI does not expose DELETE because the platform is
append-only. Where the API exposes disable commands, those remain explicit
administrative operations.

## Realtime strategy

The backend provides project WebSocket and SSE transports. The current GUI
foundation uses the authenticated REST snapshot plus project event retrieval,
which is safe to reconcile and easy to test. A dedicated realtime adapter must
add WebSocket-first transport with SSE fallback without moving domain logic
into Streamlit.

The reconciliation rule is:

`REST snapshot -> event stream -> targeted refresh -> REST reconciliation`

## Explicit boundary

Worker protocol endpoints (`claim`, `heartbeat`, `complete`) are machine
protocols and are not presented as human-facing task buttons.

The dashboard must use canonical mounted routers only. Retired legacy surfaces
such as `/actors`, `/tasks`, `/artifacts`, `/capabilities` and similar routes
must not be reintroduced through the GUI.
