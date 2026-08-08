# Phase 4 AI-4 — Execution Engine

## Purpose

AI-4 is the execution boundary after AI-1 identity, AI-2 context and AI-3 authority. It performs a bounded operation only when an explicit AI-3 `ALLOW` decision covers the exact request.

```text
AI-1 Identity
     |
AI-2 Context
     |
AI-3 Authority
     |
     | explicit ALLOW / DENY
     v
AI-4 Execution
     |
     +--> trusted action adapter
     |
     +--> immutable execution audit
```

## Security contract

1. Missing authority is rejected.
2. A `DENY` decision is never executed.
3. Request ID, identity, action, resource and context packet ID must match the authority decision exactly.
4. AI-4 never evaluates policy rules and never turns capabilities into authority.
5. Only explicitly registered adapters may execute an action.
6. Duplicate authorized execution identities are idempotent; the adapter is not invoked twice.
7. Adapter failures become immutable `FAILED` audit records.
8. Every accepted, rejected, failed and replayed attempt is auditable.
9. Execution records and requests are immutable value objects.
10. An adapter receives a bounded `ExecutionRequest`, not a shell command or arbitrary code string.

## Adapter model

An adapter is a trusted implementation registered for one exact action. Registration is application-owned and explicit. Agents cannot register adapters through an execution request.

The reference `StaticExecutionAdapter` exists for deterministic tests and integration scaffolding. Production adapters should wrap narrowly scoped domain services rather than a general-purpose shell.

## Idempotency

The execution ID is a SHA-256 digest of the request's security-relevant fields, parameters and the exact authority decision/policy binding. Repeating the same authorized request returns a `REPLAYED` record without invoking the adapter again.

The decision effect itself is included in the identity and `DENY` is checked before replay lookup. This prevents a later denial from ever replaying an earlier success.

## Failure model

```text
missing decision      -> REJECTED
DENY decision         -> REJECTED
binding mismatch      -> REJECTED
no adapter            -> REJECTED
adapter exception     -> FAILED
successful adapter    -> SUCCEEDED
same authorized work  -> REPLAYED
```

## Explicit non-responsibilities

AI-4 does not:

- grant authority;
- modify AI-1 identity records;
- modify AI-2 context packets;
- evaluate or override AI-3 policy;
- accept an agent-supplied executable command;
- silently retry a failed operation;
- bypass the audit trail.

The core invariant is:

`AI-4 execution != AI-3 authority`
