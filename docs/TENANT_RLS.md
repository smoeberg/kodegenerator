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

## Deployment

1. Back up the database and validate restore before applying the migration.
2. Deploy session-aware application code and migration together.
3. Run `alembic upgrade head` as the table owner.
4. Verify Tenant A cannot select, update, or insert Tenant B rows using the
   application database role.
5. Verify connection-pool reuse does not preserve the previous tenant.
6. Roll back extended Pipeline/Council enforcement with
   `alembic downgrade 015_core_tenant_rls`. Roll back all RLS enforcement with
   `alembic downgrade 014_identity_principals`. Either rollback requires a
   controlled maintenance window because it removes database isolation.

Identity principals are intentionally global authentication records. Runtime
queue and execution-replay tables do not yet contain `organization_id`; they
remain outside the RLS boundary and must not be described as tenant-isolated
until a datamodel migration supplies an enforceable tenant key.
