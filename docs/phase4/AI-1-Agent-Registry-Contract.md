# DOR Phase 4 — AI-1 Agent Registry Contract

## Purpose

AI-1 is the **identity and discovery layer** for agents in DOR.

It answers:

> **Who is this agent, what does it declare, and where can it be found?**

It does **not** answer:

> **Is this agent allowed to perform this action?**

That decision belongs to **AI-3 Governance & Capability Engine**.

## Contract

An agent registration contains:

- stable `AgentIdentity`
- agent type
- semantic version
- declared role
- declared capabilities
- optional trust-anchor reference
- registration actor and timestamp
- lifecycle state

The registration record is immutable. Lifecycle changes create a replacement record and an audit event rather than mutating the existing record in place.

## Identity

Identity is a deterministic SHA-256 digest of a canonical declaration:

`agent_type + version + role + sorted capabilities + trust_anchor`

Therefore:

- identical declarations produce identical identities
- declaration changes produce a different identity
- capability ordering does not change identity
- trust-anchor changes produce a different identity

Identity is **not** an authorization credential.

## Capability Boundary

AI-1 stores capability declarations. It deliberately does not maintain an allowlist and does not grant permissions.

This prevents the registry from becoming an accidental authority layer.

The intended Phase 4 flow is:

`AI-1 Identity → AI-2 Context → AI-3 Authority → AI-4 Execution`

AI-3 may consult AI-1, but AI-1 cannot approve an operation merely because an agent declares a capability.

## Lifecycle

Supported lifecycle operations:

1. register
2. discover/query
3. deactivate
4. audit

Deactivation preserves the identity and audit history.

## Security Properties

- deterministic identity
- immutable records
- fail-closed validation
- explicit provenance
- no arbitrary execution
- no LLM-generated authority
- no authorization decisions
- no verification PASS/FAIL decisions

## Phase 3 Boundary

AI-1 does not modify Phase 3 verification, distribution, routing, contract compilation, or orchestration contracts.

Integration with those components should be introduced only through explicit contracts after the AI-1 core has passed independent tests.

## Acceptance Criteria

- [ ] deterministic identity is tested
- [ ] identity is order-independent for capabilities
- [ ] records cannot be mutated after registration
- [ ] invalid registration leaves registry unchanged
- [ ] duplicate identity is rejected
- [ ] discovery supports role and capability queries
- [ ] deactivation preserves identity and audit history
- [ ] capability declaration is not treated as authorization
- [ ] no Phase 3 source files are modified
