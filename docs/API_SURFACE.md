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
- Bot Governance, Bot Selection, and read-only Bot Evidence

Health and token issuance are the only intentionally unauthenticated HTTP
boundaries. The internal Swarm dashboard module is not mounted.

## Governed multi-bot evidence

`/api/v1/bot-evidence` is an authenticated, organization-scoped, read-only
surface for immutable evaluation, performance, factory-candidate, and
integration evidence. Every response contains the organization, evidence
type, immutable ID, verified fingerprint, and its structured payload.

The durable store reconstructs and fingerprint-validates the domain object
before it is returned. Callers cannot mutate evidence through this router, and
provider credentials or secret values are never included in its payloads.

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
