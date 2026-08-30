# PostgreSQL tenant isolation

Migration `015_core_tenant_rls` enables and forces PostgreSQL row-level
security for the canonical runtime persistence core. SQLite remains suitable
for tests and local development but does not provide database-enforced tenant
isolation.

## Session contract

All canonical tenant work must open a session with:

```python
with database.session(organization_id) as session:
    ...
```

On PostgreSQL this executes transaction-local `set_config` for
`dor.organization_id`. The policy uses that value for both row visibility and
write checks. An absent setting matches no organization. The value is local to
the transaction and is not retained when a pooled connection is reused.

Unscoped sessions are permitted only for non-tenant system operations, such as
creating the organization catalog entry and checking database readiness. They
cannot read or mutate the RLS-protected tables.

## Covered tables

- `actors`
- `role_definitions`
- `role_assignments`
- `workflows`
- `projects`
- `domain_events`
- `command_executions`
- `task_executions`
- `pipeline_runtime_states`
- `governed_llm_calls`
- `terminal_side_effects`
- `council_sessions`
- `council_disputes`
- `council_votes`
- `council_evidence_bindings`
- `council_failure_observations`
- `council_outbox_events`
- `runtime_queue_messages`
- `execution_replay_ledger`

## Deployment

1. Back up the database and validate restore before applying the migration.
2. Deploy session-aware application code and migration together.
3. Run `alembic upgrade head` as the table owner.
4. Verify Tenant A cannot select, update, or insert Tenant B rows using the
   application database role.
5. Verify connection-pool reuse does not preserve the previous tenant.
6. Before migration `017_queue_replay_tenant_scope`, drain or explicitly
   archive both queue and replay tables. The migration refuses non-empty
   tables because their legacy rows have no trustworthy tenant owner.
7. Roll back queue/replay enforcement only after draining those tables with
   `alembic downgrade 016_extended_tenant_rls`. Roll back extended
   Pipeline/Council enforcement with
   `alembic downgrade 015_core_tenant_rls`. Roll back all RLS enforcement with
   `alembic downgrade 014_identity_principals`. Either rollback requires a
   controlled maintenance window because it removes database isolation.

Identity principals are intentionally global authentication records. Runtime
queue messages and execution replay records use `(organization_id, logical_id)`
composite primary keys, so different organizations may safely use the same
logical message or execution identifier.
