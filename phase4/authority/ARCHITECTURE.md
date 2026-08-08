# Phase 4 AI-3 — Authority Engine

## Purpose

AI-3 is the authority boundary between declared agent identity/context and execution. It answers one question:

> May this identified agent perform this concrete action on this concrete resource under the supplied context and policy?

It returns only an explicit `ALLOW` or `DENY` decision. It does not execute the action.

## Layer separation

```text
AI-1 Identity
    |
    | identity + declared capabilities
    v
AI-2 Context
    |
    | bounded context packet
    v
AI-3 Authority
    |
    | ALLOW / DENY
    v
AI-4 Execution
```

The following distinctions are contractual:

- identity is not authority;
- declared capability is not authority;
- context is input to evaluation, not a permission grant;
- an authority decision is not an execution command.

## Decision rules

1. A request must identify the agent, action, resource and AI-2 context packet.
2. A policy must contain explicit immutable rules.
3. A matching rule must explicitly state `ALLOW` or `DENY`.
4. No matching rule results in `DENY`.
5. If both ALLOW and DENY rules match, `DENY` wins.
6. Agent identity and role restrictions are explicit policy predicates.
7. Context restrictions are explicit key/value predicates.
8. The engine never consults declared capabilities as authority.
9. The engine never executes commands or mutates state outside its audit log.
10. Every evaluation creates an immutable, auditable `AuthorityDecision`.

## Rule matching

A rule matches when all supplied predicates match:

- action is exact;
- resource matches the explicit resource pattern;
- optional agent identity matches exactly;
- optional agent role matches exactly;
- every required context key has the expected value.

Rules are evaluated deterministically. Priority orders matched rules for audit readability, but priority can never make an explicit DENY lose to an ALLOW.

## Fail-closed contract

```text
no rule       -> DENY
DENY + ALLOW  -> DENY
DENY only     -> DENY
ALLOW only    -> ALLOW
```

There is no implicit permission.

## Audit contract

Every decision records:

- request ID;
- agent identity;
- action;
- resource;
- AI-2 context packet ID;
- policy ID and version;
- matched rule IDs;
- decision;
- reason;
- evaluation timestamp.

This allows a later reviewer to reconstruct why an action was allowed or denied without granting AI-3 execution authority.

## Explicit non-responsibilities

AI-3 does not:

- create or modify agent identities;
- grant capabilities;
- interpret a capability claim as authorization;
- make P3-20 verification PASS/FAIL decisions;
- generate policies through an LLM;
- execute shell commands or application actions;
- bypass AI-1 or AI-2;
- call AI-4 itself.

## Security invariant

The core invariant is:

`declared_capability != authority`

An agent may declare `read_file`, but AI-3 returns `ALLOW` only when an applicable authority rule explicitly permits the concrete read request.
