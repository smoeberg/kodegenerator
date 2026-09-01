# Docker deployment status

The only supported target for the forthcoming DOR demo is
`compose.demo.yml`. The architecture and certification criteria are defined in
`docs/DEMO_INSTALLATION_CONTRACT.md` and
`ci/manifests/demo_installation_contract.json`.

## Current status

The Compose topology is implemented but **not demo-certified yet**. Queue
wiring, authenticated worker identity, tenant-scope remediation, consolidated
startup validation, attested release gates, and the clean-room Docker test are
still required.

Do not expose this stack to untrusted networks or describe it as production
ready.

## Configuration preparation

Copy the environment template and replace every `generated-*` placeholder:

```bash
cp .env.demo.example .env
```

Generate the Fernet key as documented in the template. Use URL-safe characters
for the PostgreSQL password because it is interpolated into a SQLAlchemy URL.
Never commit `.env`.

## Canonical commands

After the remaining certification phases are complete, start with:

```bash
docker compose -f compose.demo.yml up --build -d
```

Inspect services:

```bash
docker compose -f compose.demo.yml ps
docker compose -f compose.demo.yml logs --tail=200
```

Stop without deleting PostgreSQL or artifact data:

```bash
docker compose -f compose.demo.yml down
```

The intended public surfaces are:

- API health: `http://localhost:8000/health`
- API readiness: `http://localhost:8000/health/ready`
- API documentation: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8501`

## Container lifecycle

The `migrate` service is the only migration owner. It upgrades the database and
creates the configured artifact bucket before API and worker startup. Runtime
containers do not run migrations themselves.

The API, worker, migration, and dashboard use the same non-root runtime image.
Their root filesystems are read-only and Linux capabilities are dropped. API
and dashboard receive explicit writable `/tmp` filesystems.

## Legacy files

These files are retained temporarily for compatibility and reference, but are
not supported demo entrypoints:

- `docker-compose.yml`
- `docker-compose.prod.yml`
- `docker-compose.production.yml`
- root `Dockerfile`
- `docker/Dockerfile.api`
- `docker/Dockerfile.worker`

They must not be combined with `compose.demo.yml`.
