# Phase 3: Tenant-scoped Swarm control

Phase 3 removes process-local project ownership and pause state from the Swarm
HTTP surface. Dispatch now starts from an existing canonical Control Plane
project and remains bound to the authenticated organization throughout the
queue, status, WebSocket, and SSE paths.

## Runtime contract

- Access tokens carry the principal's durable `organization_id` claim.
- A Swarm dispatch may only reference a canonical `projects` row in that
  organization and may only be registered by its `created_by` principal.
- Dispatch registrations are immutable and idempotent.
- Pause state is durable and scoped per organization.
- Database-backed pipeline registries and queues are selected per authenticated
  organization; an environment default is only used by non-HTTP workers.
- Project status counts only tasks whose metadata matches both organization and
  project.
- WebSocket and SSE authorization revalidates the same organization-bound
  project ownership as HTTP.

## Migration and rollback

Revision `025_swarm_control_state` adds the identity organization binding,
tenant-scoped dispatch and control tables, composite project ownership, and
forced PostgreSQL RLS policies. The identity column remains nullable during the
upgrade so existing principals are not assigned invented ownership.

Rollback is intentionally fail-closed. The downgrade refuses to drop non-empty
Swarm control tables; operators must drain or explicitly migrate the state
before returning to revision `024_worker_service_identities`.

## Required configuration

Demo and production bootstrap identities require
`DOR_ADMIN_ORGANIZATION_ID`. Database-backed workers still require
`DOR_PIPELINE_STATE_ORGANIZATION_ID`; that value identifies the single tenant a
worker process is authorized to serve.
