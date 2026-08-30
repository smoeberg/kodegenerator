# Canonical API surface and legacy retirement

The public DOR API is allowlisted in `api/api_surface.py` and mounted by
`api/main.py`. Authentication is applied to every canonical HTTP router as a
router dependency. The realtime router performs bearer-token and project
authorization before accepting WebSocket or SSE traffic.

## Supported authenticated routers

- Control Plane
- Swarm and Swarm Operations
- Workflows
- Implementation Agent
- Decisions
- Pipeline and Pipeline Gates

Health and token issuance are the only intentionally unauthenticated HTTP
boundaries. The internal Swarm dashboard module is not mounted.

## Retired endpoints

The former task, artifact, actor, organization, capability, intent, role,
workflow-template, and governance-gate endpoints were removed in production
hardening Phase 3. They performed global ID-only persistence lookups and could
not meet the canonical organization-context invariant.

Do not restore these modules or prefixes. A replacement endpoint must:

1. derive principal and organization context from verified authentication;
2. use organization-scoped repository methods;
3. pass cross-tenant denial and canonical-inventory tests;
4. enter the explicit inventory through security review; and
5. avoid accepting organization or actor identity as an untrusted substitute
   for the authenticated context.
