# AI-2 Context Packet Engine

## Boundary

AI-2 converts already-available, eligible information into a deterministic and bounded context packet for an agent.

The authority boundary is explicit:

- **AI-1 Agent Registry**: identity and declared capabilities.
- **AI-2 Context Packet Engine**: context selection, normalization, provenance, ordering and bounds.
- **AI-3 Governance / Capability Engine**: authority and permission decisions.
- **AI-4 Agent Execution Adapter**: execution.

AI-2 does **not** authorize an agent, execute commands, or reinterpret a declared capability as permission.

## Contract

`ContextRequest` declares:

- target agent identity
- purpose
- optional requested keys
- maximum item count
- maximum serialized-size budget
- permitted sensitivity classes

`ContextItem` carries:

- source
- key
- value
- relevance score
- provenance
- sensitivity classification

`ContextPacket` is an immutable snapshot containing the selected items and a deterministic packet identity.

## Determinism

Items are ordered by:

1. relevance descending
2. source ascending
3. key ascending

The packet identity is SHA-256 over canonical JSON of the target agent, purpose and selected items. Therefore identical semantic inputs produce the same packet identity regardless of source iteration order.

The packet timestamp is metadata only and is deliberately excluded from packet identity.

## Bounds and Fail-Closed Behavior

AI-2 never emits an unbounded packet. Selection stops at the request's item and byte budgets. If input is malformed, the engine rejects the build rather than silently coercing it.

When eligible context exceeds the budget, the packet is marked `truncated=True`. This is explicit and auditable; downstream components must not assume that the packet is complete.

## Security / Trust Boundary

Sensitivity filtering is an input constraint, not an authorization system. AI-2 does not decide whether an agent is entitled to sensitive data. The caller must provide only context that is already eligible under the system's authority model.

Similarly, a context value such as `declared_capability=execute` remains data. AI-2 never converts it into an `authorized=True` decision.

## Provenance

Each context item retains its source and provenance. Each packet build is recorded in the engine audit trail with agent identity, actor, timestamp, item count and truncation state.

## Non-Goals

- No authorization decisions.
- No capability grants.
- No command generation.
- No arbitrary code execution.
- No LLM dependency.
- No modification of AI-1 or Phase 3 authority boundaries.

## Production Follow-Up

The reference implementation is intentionally in-memory and synchronous. A later persistence/provider layer can supply context items from durable sources without changing the packet contract.
