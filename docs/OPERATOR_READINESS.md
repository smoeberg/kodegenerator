# Operator readiness gate

This runbook defines the read-only post-deploy verification for the canonical
Docker Compose runtime. It complements `RUNBOOKS.md` and `FIRE_DRILL.md`; it does
not replace staging certification, rollback, or the quarterly real backup
restore drill.

## Goal

An operator should be able to answer **"is this deployed DOR instance ready to
serve operators now?"** without inferring from container presence alone.

The canonical command is:

```bash
make operator-readiness
```

The command prints one JSON report and exits:

- `0` only when classification is `READY`;
- `1` when classification is `NOT_READY`.

The report contains check names and non-secret diagnostic summaries. It never
prints configured credentials, database URLs, JWT keys, or response bodies from
failed endpoints.

## Preconditions

1. Run from the exact repository revision used for the deployment.
2. `docker compose` can inspect the deployed Compose project.
3. The API and dashboard health endpoints are reachable from the operator host.
4. The deployment has completed its `migrate` one-shot service.

Defaults target the local Compose ports:

- API: `http://127.0.0.1:${DOR_API_PORT:-8000}`
- dashboard: `http://127.0.0.1:${DOR_DASHBOARD_PORT:-8501}`
- Compose file: `compose.yml`

For another host or reverse proxy, set:

```bash
export DOR_READINESS_API_URL=https://dor-api.example.com
export DOR_READINESS_DASHBOARD_URL=https://dor.example.com
make operator-readiness
```

`DOR_COMPOSE_FILE` may point to another Compose file when the deployment uses an
explicit production override.

## Checks

The gate is fail-closed and verifies all of the following.

### 1. Docker build-context hygiene

`.dockerignore` must exclude:

- `.git`;
- `.env`;
- common `.env.*` variants such as `.env.local`, `.env.production`, and
  `.env.demo`.

This prevents local deployment secret files from being copied by the runtime
Dockerfile's broad source `COPY` instruction.

### 2. Compose runtime state

`docker compose ps --all --format json` must show these long-running services as
`running` and `healthy`:

- `postgres`
- `minio`
- `api`
- every `worker` replica
- `dashboard`
- `otel-collector`

The one-shot `migrate` service must be `exited`/`completed` with exit code `0`.
A missing service, unhealthy replica, failed migration, unavailable Docker CLI,
or invalid Compose JSON makes the deployment `NOT_READY`.

### 3. API liveness

`GET /health` must return HTTP 200 with the canonical payload:

```json
{"status": "ok"}
```

### 4. API readiness and schema state

`GET /health/ready` must return HTTP 200 and report:

- `status == "ready"`
- `database == "ok"`
- `migration_head` exactly equal to `docs/CURRENT_STATE.json`'s
  `canonical_alembic_head`

This prevents an operator from accepting a deployment whose API process is
alive while the database schema is stale or divergent.

### 5. Dashboard health

`GET /_stcore/health` must return HTTP 200 with `ok`.

## Reading the report

Example green result (abbreviated):

```json
{
  "classification": "READY",
  "errors": [],
  "checks": [
    {"name": "build_context", "status": "PASS", "detail": "..."},
    {"name": "compose:api", "status": "PASS", "detail": "..."},
    {"name": "api_readiness", "status": "PASS", "detail": "..."},
    {"name": "dashboard_health", "status": "PASS", "detail": "..."}
  ]
}
```

Any failed check changes the classification to `NOT_READY`; do not mark the
deployment operational until the failure is resolved or the deployment is
rolled back through the existing governed runbook.

## Failure response

| Failed check | Operator action |
|---|---|
| `build_context` | Do not rebuild/publish the image; fix `.dockerignore` first. |
| `compose_ps` | Verify Docker/Compose access and the intended Compose project/file. |
| `compose:migrate` | Stop rollout; inspect migration logs and database state. |
| `compose:<service>` | Inspect that service's health/logs; do not infer readiness from `running` alone. |
| `api_liveness` | Treat the API as unavailable; inspect API container/startup logs. |
| `api_readiness` | Treat as fail-closed schema/database drift; do not serve traffic. |
| `dashboard_health` | Keep the operator UI out of service until Streamlit is healthy. |

For an uncertified or drifted staging digest, use `R-09` through `R-11` in
`RUNBOOKS.md`. For recovery after data loss, use `R-05` and perform a real
restore into a fresh target. `scripts/fire_drill.sh` remains the reconciliation
fire drill and its restore step is only a tooling smoke check unless the
quarterly host-dependent restore procedure is executed separately.

## Operational evidence

Archive the JSON report with the deployment/change record together with:

- deployed source revision or image digest;
- timestamp;
- operator/change identifier;
- result of staging certification/reconciliation when applicable.

A `READY` report is post-deploy evidence, not release authority: branch
protection, staging certification, backend governance, and the existing fire
and restore drills remain separate controls.
