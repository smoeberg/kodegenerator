# Pipeline persistence and migrations

Phase 3 moves pipeline snapshots and governed LLM replay receipts into the
canonical SQLAlchemy/Alembic database. File snapshots remain available for
local compatibility, but production workers should share one database.

## Migration

Revision `012_pipeline_persistence` creates:

- `pipeline_runtime_states`: organization-scoped, revisioned orchestrator
  snapshots;
- `governed_llm_calls`: organization-scoped replay receipts with lease expiry
  and fencing tokens.

Apply the canonical migration head before workers start:

```bash
alembic upgrade head
```

Rollback of revision 012 itself deletes both tables and their receipts. Back up
the database before any downgrade. Application startup already invokes the
canonical Alembic upgrade through `DORRuntime.boot()`.

## Tenant boundary

Pipeline registry identity is an organization boundary, not a deployment-wide
default. Canonical API and worker paths must pass the authenticated
`organization_id` explicitly to `get_pipeline_registry(...)` before reading or
mutating workflow, queue, gate, or snapshot state.

In `demo` and `production`, an unscoped registry lookup fails closed. A worker
using the database queue must authenticate to one organization and is started
with that exact organization scope. A workflow from another organization must
not be visible through that registry even when its workflow ID is known.

`DOR_PIPELINE_STATE_ORGANIZATION_ID` remains a compatibility setting for direct
legacy `PipelineOrchestrator` construction. It is not an authorization source
for canonical HTTP or authenticated worker paths.

## Configuration

```bash
export DATABASE_URL='postgresql+psycopg://dor:...@db/dor'
export DOR_PIPELINE_DATABASE_URL="$DATABASE_URL"
export DOR_PIPELINE_STATE_STORE_ID='pipeline-default'
export DOR_PIPELINE_LLM_LEASE_SECONDS=180

# Authenticated worker tenant binding
export DOR_WORKER_ORGANIZATION_ID='org-acme'
```

API requests establish organization membership through the canonical runtime
context before selecting the tenant registry. Database workers derive their
registry scope from their authenticated `WorkerPrincipal.organization_id`.

## Concurrency and recovery

Pipeline snapshots use optimistic revisions. A stale worker cannot overwrite a
newer state and receives `PipelineStateConflictError`.

Each tenant registry owns a tenant-scoped database queue and a tenant-scoped
`pipeline_runtime_states` row for the configured store ID. Recreating API or
worker processes therefore restores only that organization's snapshot and
republishes only that organization's unfinished tasks.

Before an LLM provider call, a worker atomically claims the tuple
`(organization_id, idempotency_key)`. A second worker either:

- replays the completed, schema-validated result;
- is rejected while the first lease is valid; or
- recovers an expired lease with a new fencing token.

Completion requires the current fencing token, so a recovered/stale worker
cannot overwrite the winner. Provider failures are recorded by failure class
and become immediately recoverable; prompts, secrets and raw provider envelopes
are never persisted.

## Operational checks

1. Run `alembic current` and verify the repository's canonical migration head.
2. Start two organization-scoped registries against the same database and verify
   workflow IDs, queue claims, and snapshots do not cross organizations.
3. Restart API/worker processes and verify each organization restores only its
   own workflows and pending tasks.
4. Replay an LLM task ID and verify `replayed=true` with no provider request.
5. Alert on long-lived `governed_llm_calls.status = 'in_progress'` rows.
6. Treat revision conflicts and stale fencing tokens as concurrency incidents,
   not as retryable writes with overwritten state.
