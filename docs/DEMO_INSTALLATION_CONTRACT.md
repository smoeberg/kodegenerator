# DOR demo installation contract

Status: **Compose implementation present; runtime certification pending**
Contract ID: `dor-demo-installation-v1`

This document defines the only supported installation target for the DOR
demonstration. It does not certify the current Docker files. Certification is
earned only after the executable criteria below pass against the assembled
containers.

The machine-readable source of truth is
`ci/manifests/demo_installation_contract.json`.

## Canonical command

The canonical Compose implementation is now present. Once the remaining
runtime remediation and certification phases are complete, operators use:

```bash
docker compose -f compose.demo.yml up --build -d
```

Teardown without deleting durable data:

```bash
docker compose -f compose.demo.yml down
```

No other Compose combination is a supported demo installation. Existing
`docker-compose*.yml` files are explicitly marked as legacy development or
superseded prototype paths.

## Fixed topology

| Service | Responsibility | Public endpoint |
|---|---|---|
| `postgres` | Tenant-scoped persistence and durable queue | No |
| `minio` | Persistent generated artifacts and evidence | No |
| `migrate` | Single-owner Alembic upgrade before runtime startup | No |
| `api` | Canonical FastAPI control plane | `localhost:8000` |
| `worker` | Durable, fenced execution pool | No |
| `dashboard` | Streamlit GUI over canonical APIs | `localhost:8501` |
| `otel-collector` | API and worker telemetry | No |

PostgreSQL is mandatory. SQLite, process-local queues, and JSON pipeline state
are prohibited in the certified demo path. The API and workers must share the
same PostgreSQL-backed queue and artifact store.

## Architectural invariants

1. The GUI uses authenticated canonical HTTP APIs and does not write directly
   to SQLite or internal repository models.
2. A dedicated migration service reaches the canonical Alembic head before API
   or worker startup.
3. Worker identity is bound to an authenticated service identity; a request
   body is not authoritative identity evidence.
4. Queue claim, heartbeat, completion, retry, and dead-letter operations are
   scoped by organization and protected by leases plus fencing tokens.
5. API and worker containers use non-root users and read-only root filesystems.
6. Missing production-equivalent configuration fails startup without printing
   secret values.
7. No release or deployment is reported successful without authority and
   attested evidence bound to the exact candidate.

## Required configuration

The demo environment file must explicitly provide:

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `DOR_ADMIN_PASSWORD`
- `DOR_JWT_SIGNING_KEYS`
- `DOR_JWT_ACTIVE_KEY_ID`
- `DOR_AUTHORITY_SIGNING_KEY`
- `DOR_ENCRYPTION_KEY`
- `DOR_WORKER_CAPABILITIES`

Example files must contain non-functional placeholders. The runtime must reject
placeholder fragments such as `change-me`, `replace-with`, and `placeholder`.

## Phase boundaries

The Compose implementation now supplies the fixed service topology, shared
runtime image, migration owner, dashboard, healthchecks, ports, PostgreSQL and
MinIO persistence. This does not certify the runtime behavior.

The next phase must wire the canonical database queue and authenticated worker
identity. Later phases must close tenant context, startup validation, attested
release gates, and Docker certification.

## Certification gate

The demo remains **not certified** until an automated clean-room test proves:

- clean database migration to the canonical head;
- healthy API, readiness endpoint, dashboard, workers, PostgreSQL, and MinIO;
- task delivery from API to a separate worker container;
- cross-tenant denial;
- stale-worker fencing and restart recovery;
- exactly one terminal side effect for one logical operation;
- live dashboard data from the API, without mock fallback; and
- release evidence derived from actual CI jobs.

Passing unit tests or `docker compose config` alone is insufficient.
