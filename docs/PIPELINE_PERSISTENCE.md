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

Apply the migration before workers start:

```bash
alembic upgrade head
```

Rollback of this revision deletes both new tables and their receipts:

```bash
alembic downgrade 011_council_runtime
```

Back up the database before downgrading. Application startup already invokes
the canonical Alembic upgrade through `DORRuntime.boot()`.

## Configuration

```bash
export DATABASE_URL='postgresql+psycopg://dor:...@db/dor'
export DOR_PIPELINE_DATABASE_URL="$DATABASE_URL"
export DOR_PIPELINE_STATE_ORGANIZATION_ID='org-acme'
export DOR_PIPELINE_STATE_STORE_ID='software-factory'
export DOR_PIPELINE_LLM_LEASE_SECONDS=180
```

`DOR_PIPELINE_STATE_ORGANIZATION_ID` is mandatory whenever database-backed
pipeline state is enabled. A deployment must not configure the same logical
pipeline namespace with different organization IDs.

## Concurrency and recovery

Pipeline snapshots use optimistic revisions. A stale worker cannot overwrite a
newer state and receives `PipelineStateConflictError`.

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

1. Run `alembic current` and verify `012_pipeline_persistence`.
2. Restart a worker and verify an existing workflow is restored.
3. Replay an LLM task ID and verify `replayed=true` with no provider request.
4. Alert on long-lived `governed_llm_calls.status = 'in_progress'` rows.
5. Treat revision conflicts and stale fencing tokens as concurrency incidents,
   not as retryable writes with overwritten state.
