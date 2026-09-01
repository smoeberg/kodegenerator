# Phase 4: Demo startup and readiness

The demo and production environments now share one fail-closed startup
configuration boundary. Every application container declares its runtime role
and validates its complete wiring before migrations, API startup, worker
claims, or dashboard startup can begin.

The validator enforces PostgreSQL-only shared persistence, the database queue,
absolute artifact/API endpoints, role-specific identity configuration, valid
Fernet and JWT key material, minimum authority/worker secret lengths, and
rejection of documentation placeholders. Error messages identify configuration
names but never include their values.

API readiness is distinct from liveness. `/health` only proves that the process
is alive. `/health/ready` connects to the configured `DATABASE_URL` and requires
the database's `alembic_version` to equal the canonical head recorded in
`docs/CURRENT_STATE.json`. A missing, stale, divergent, or unreachable schema
returns HTTP 503 and prevents Compose from marking the API healthy.
