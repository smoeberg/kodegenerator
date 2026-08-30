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

## Deployment

1. Back up the database and validate restore before applying the migration.
2. Deploy session-aware application code and migration together.
3. Run `alembic upgrade head` as the table owner.
4. Verify Tenant A cannot select, update, or insert Tenant B rows using the
   application database role.
5. Verify connection-pool reuse does not preserve the previous tenant.
6. Roll back with `alembic downgrade 014_identity_principals` only during a
   controlled maintenance window; this removes the database enforcement.

Pipeline, Council, identity, and operational stores are explicitly outside
this first RLS boundary. Their existing organization filters remain required;
they must not be described as database-enforced until their session factories
adopt the same transaction-local context.
