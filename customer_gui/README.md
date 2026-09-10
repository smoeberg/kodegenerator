# DOR Customer Portal

GUI-02 is a separate customer-facing Streamlit application. It is a projection
and decision interface over existing DOR API contracts, not a second runtime or
authority system.

Run locally against an available DOR API:

```bash
streamlit run customer_gui/app.py --server.port 8502
```

Or add the customer service to the normal stack with the compose overlay:

```bash
docker compose -f compose.yml -f compose.customer.yml up customer-portal
```

The portal uses existing authenticated, tenant-scoped API contracts for project
catalogs, project events and project-bound executions. Customer decisions use
the existing execution gate endpoints; the portal never calls execution start,
advance, proposal creation, Patch Apply, deployment or release endpoints.

## Known backend contract gaps

The current backend does not expose a persisted customer-readable Plan object or
Plan ID. The active project contract exposes only the exact active plan request
fingerprint, so the portal labels it as a fingerprint and does not invent a Plan
ID or reconstruct Plan content.

The current execution Proposal endpoint provides workflow-scoped proposal
artifacts, but no authoritative Proposal-to-gate/Decision relationship or
Proposal-specific evidence link. The portal therefore does not fabricate those
edges.

Fine-grained customer roles such as Viewer versus Decision Maker are not exposed
by the existing execution gate authorization contract. Every decision request
is still server-authorized, but GUI-02 does not manufacture a client-side role
model. Adding such roles requires a separate backend authority contract.

The execution gate endpoint exposes the current resolved gates, but not a complete
persisted, timestamped decision ledger. Project lifecycle history is rendered
from the canonical project-events API and resolved gates are shown without
invented timestamps; the missing full-history contract is surfaced as a limitation.

The current gate/Proposal contracts do not provide a customer recommendation,
consequence model or authoritative Proposal-specific evidence relationship. The
portal shows descriptions and evidence only where those fields are actually
provided instead of synthesizing a recommendation or causal link.

The project-scoped execution read endpoint requires the project to still be
active. Historical execution/proposal retrieval for completed or archived
projects therefore remains a backend contract gap.
