# P3-22 — Orchestrator Contract

## Status

Implementation-ready contract. P3-22 coordinates the existing deterministic Phase 3 boundaries; it is not an authority for routing, execution, or verification.

## Pipeline

```text
Task
  ↓
P3-19 Distribution → DispatchRecord
  ↓
Specialist delivery → DeliveredProduct
  ↓
P3-21 Execution → Evidence
  ↓
P3-20 Verification → PASS / FAIL
  ↓
P3-22 Orchestrator → lifecycle outcome
```

## Authority boundaries

- P3-19 is the sole authority for deterministic specialist dispatch.
- P3-21 is the execution boundary and may execute only trusted, immutable adapters.
- P3-20 is the sole authority for verification `PASS` / `FAIL`.
- P3-22 coordinates these boundaries but MUST NOT reproduce or override their decisions.
- No LLM may choose commands, alter fingerprints, or determine verification status.

## Lifecycle

Normal path:

`RECEIVED → DISPATCHED → DELIVERED → EXECUTED → VERIFIED → COMPLETED`

Failure paths:

- `DISPATCHED | DELIVERED | EXECUTED → FAILED`
- `VERIFIED → RETRYING | FAILED | ESCALATED`
- `RETRYING → DISPATCHED → DELIVERED → EXECUTED → VERIFIED`

Terminal states: `COMPLETED`, `FAILED`, `ESCALATED`.

Invalid transitions MUST be rejected.

## Core contracts

`OrchestrationRequest` is immutable and contains task identity/fingerprint, package identity/fingerprint, available inputs, selected role and an explicit retry policy.

`OrchestrationSnapshot` is an immutable lifecycle snapshot carrying the orchestration identity, state, attempt number and any available dispatch, artifact and verification fingerprints.

`OrchestrationResult` is immutable and reports the terminal lifecycle state, attempt count, preserved fingerprints and an explicit failure/escalation reason where applicable.

## Determinism and idempotency

Orchestration identity is derived deterministically from task identity/fingerprint, package identity/fingerprint, available inputs, selected role and policy identity. Replaying the same immutable request with the same policy MUST produce the same orchestration identity.

P3-22 preserves P3-19, P3-21 and P3-20 fingerprints verbatim. It does not mutate dispatches, products, evidence or verification results.

## Retry policy

There are zero implicit retries. Retry requires an explicit policy containing a bounded maximum attempt count and a retryable failure class. Each retry creates a `RETRYING → DISPATCHED` transition and executes a new evidence cycle. A P3-20 `FAIL` can never be converted to `PASS` without new execution/evidence and a fresh P3-20 decision.

When the retry budget is exhausted, the outcome is `ESCALATED` with `POLICY_EXHAUSTED`.

## Failure taxonomy

- `DISPATCH_FAILURE`
- `DELIVERY_FAILURE`
- `EXECUTION_FAILURE`
- `VERIFICATION_FAIL`
- `INFRASTRUCTURE_FAILURE`
- `POLICY_EXHAUSTED`

Execution infrastructure errors are never converted into PASS evidence.

## Acceptance criteria

- Deterministic orchestration identity.
- Explicit state machine with invalid-transition rejection.
- Zero implicit retries.
- Bounded, policy-controlled retries.
- Explicit escalation and terminal states.
- No duplicate PASS/FAIL authority.
- Fingerprint preservation across boundaries.
- No shell execution and no free command generation in P3-22.
- Tests cover happy path, invalid transitions, verification failure, bounded retry, retry exhaustion, idempotency and authority preservation.
