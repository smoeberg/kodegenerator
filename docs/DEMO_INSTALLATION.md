# Certified Demo Installation v1

## Purpose

The certified demo installation turns the production-oriented Docker Compose topology into one reproducible, operator-verifiable environment for the first real DOR product run.

It is deliberately narrower than production certification. It proves that one local demo organization can run the canonical API, workers, PostgreSQL, MinIO and Streamlit dashboard with the governed repository boundaries required by the implemented delivery chain.

The demo does **not** grant release, deploy, merge or production authority.

## Golden repository

The canonical demo repository identity is:

```text
repository:demo/golden
```

The canonical demo organization is:

```text
dor-demo-org
```

`demo/golden_repository/` is the tracked source fixture. `make demo-seed` creates two separate local Git checkouts from that fixture at one deterministic commit:

1. `.dor-demo/audit-checkouts/golden` — mounted read-only into the dashboard and selected only through the governed Project Audit checkout catalog;
2. `.dor-demo/patch-workspace` — mounted read/write only into the API and used by the governed patch runtime.

The two checkouts must have the same clean `HEAD` before the demo is READY. The browser never receives a host filesystem path and cannot turn the audit mount into the patch workspace.

## Secret and provider configuration

`make demo-seed` generates `.env.demo` with fresh local PostgreSQL, MinIO, JWT, authority, encryption, admin and worker secrets. `.env.demo` and `.dor-demo/` are gitignored and excluded from the Docker build context.

Two values are intentionally not generated because they are external provider configuration:

```bash
export OPENAI_API_KEY='...'
export DOR_IMPLEMENTATION_MODEL='...'
```

`OPENAI_API_KEY` is passed only to the API service in `compose.demo.yml`. The dashboard/browser does not receive it.

The Implementation Agent is fixed to `repository:demo/golden`. Governed patch execution is fixed to the canonical Python tool IDs:

```text
python.ruff
python.pytest
python.compileall
```

## Lifecycle

From a clean repository checkout:

```bash
export OPENAI_API_KEY='...'
export DOR_IMPLEMENTATION_MODEL='...'
make demo-seed
make demo-preflight
make demo-up
make demo-certify
```

Useful lifecycle commands:

```bash
make demo-down
make demo-reset
```

`demo-reset` removes Docker Compose volumes and restores both demo workspaces to the deterministic golden baseline while retaining the generated `.env.demo` credentials.

## Preflight contract

`make demo-preflight` is read-only after seeding. It fails closed unless all of the following are true:

- every required non-placeholder demo variable is present;
- the Implementation Agent resource is exactly `repository:demo/golden`;
- the governed patch tool allowlist is exactly the canonical Python toolchain;
- the audit checkout catalog binds the golden repository to `dor-demo-org`;
- audit and patch workspaces are clean Git checkouts at the same commit;
- `.dockerignore` excludes common secret files and `.git`;
- `compose.yml + compose.demo.yml` renders successfully;
- the dashboard resolves the API through canonical `DOR_API_URL=http://api:8000`;
- the API patch runtime points to `/demo/patch-workspace`;
- the API Implementation Agent scope remains the golden repository.

The command prints only check names/status/details. It never prints configured secret values.

## Certification contract

After `make demo-up`, run:

```bash
make demo-certify
```

A `CERTIFIED` result additionally requires:

- PostgreSQL, MinIO, API, worker replicas, dashboard and OTEL collector are running and healthy;
- the one-shot migration service completed successfully;
- `/health` reports API liveness;
- `/health/ready` reports the exact canonical Alembic head from `docs/CURRENT_STATE.json`;
- Streamlit health reports `ok`;
- the generated admin credential can authenticate and use the protected API surface;
- inside the API container, both `get_implementation_agent_runtime()` and `get_governed_patch_runtime()` construct successfully;
- inside the dashboard container, the governed Project Audit catalog resolves the exact demo organization/repository binding.

Certification intentionally does **not** call the external model provider. It verifies installation/configuration readiness, not model behavior or delivery effectiveness.

## Relationship to Golden Run

The next milestone is the Golden Real Pipeline Run. That run uses the certified installation to perform a real user-visible task against `repository:demo/golden`, capture the delivery evidence chain and establish the first development-time benchmark.

Therefore:

```text
Certified Demo Installation
        !=
Golden Run success
        !=
2x development-time evidence
        !=
production certification
```

Each is a separate boundary.
