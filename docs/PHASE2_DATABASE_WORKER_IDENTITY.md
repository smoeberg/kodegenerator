# Phase 2: database queue and worker service identity

The production worker path uses one tenant-scoped database queue for
API publication and worker claims. Local SQLite and in-memory queues remain
development-only compatibility backends.

## Identity boundary

Workers authenticate with a provisioned service account:

- `DOR_WORKER_ORGANIZATION_ID`
- `DOR_WORKER_SERVICE_ID`
- `DOR_WORKER_CREDENTIAL`
- a container instance ID (`DOR_WORKER_INSTANCE_ID` or hostname)

Capabilities are loaded from the persisted service identity. They are not
trusted from worker command-line arguments in the database path. The effective
claim owner is `<service_id>@<instance_id>`, and the credential is revalidated
before claims, heartbeats, completions and failures. Disabling the service
account therefore fences a running worker at its next queue transition.

The migration service provisions the configured worker identity idempotently
after Alembic completes. Provisioning refuses to overwrite a different
credential or capability set.

## Queue guarantees

- queue rows and service identities have composite tenant keys;
- PostgreSQL RLS is enabled and forced;
- claims use compare-and-set and a unique lease fencing token;
- heartbeats require the current worker and fencing token;
- stale workers cannot acknowledge reassigned work;
- completed task results remain durable;
- WBS publication is idempotent by task ID;
- dependencies and assigned capabilities are checked before a claim.

The authenticated HTTP username, never a request-body `worker_id`, owns any
legacy control-plane claim made through the HTTP compatibility endpoints.
Container workers use the service-identity path directly.
