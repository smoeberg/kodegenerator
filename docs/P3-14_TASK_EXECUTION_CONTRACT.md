# DOR P3-14 — Task Execution Boundary Contract v0.1

**Status:** Contract baseline

**Branch policy:** `main` is the sole source of truth

**Predecessor:** P3-13 Runtime/API Persistence Consolidation

**Scope:** Task lifecycle, executor selection, execution authorization boundary, deterministic task state transitions, execution receipts, and failure semantics.

---

## 1. Purpose

P3-14 establishes the canonical runtime boundary for executing a Task.

The objective is to make task execution deterministic, auditable, organization-scoped, and safe to retry without silently duplicating state changes.

P3-14 does **not** implement LLM provider integration. An executor may remain a deterministic stub until a later contract explicitly defines provider execution.

---

## 2. Canonical Execution Path

Every state-changing task execution MUST follow one canonical path:

```text
Authenticated Principal
        ↓
Organization Context
        ↓
Actor Binding
        ↓
Task Lookup
        ↓
Organization Isolation
        ↓
Task Capability Authorization
        ↓
Idempotency / Execution Receipt
        ↓
Executor Selection
        ↓
Executor Execution
        ↓
Task State Transition
        ↓
Execution Event / Audit Record
        ↓
Atomic Commit
```

No API endpoint, service, executor, or background worker may mutate task execution state by bypassing this boundary.

---

## 3. Task Identity and Organization Scope

Every executable Task MUST have an explicit organization identity.

Minimum execution identity:

```text
Task
- id
- organization_id
- workflow_id where applicable
- actor_id where applicable
- status
- task_type
```

A task from organization A MUST NOT be executable from organization B.

There MUST be no implicit organization fallback such as `"org-a"`.

Organization identity MUST be supplied explicitly by the execution context or persisted task.

---

## 4. Task State Machine

Task execution state MUST be explicit and finite.

The initial contract defines:

```text
PENDING
   ↓
RUNNING
   ├──→ SUCCEEDED
   ├──→ FAILED
   └──→ CANCELLED
```

Rules:

- `PENDING → RUNNING` requires authorization and an accepted execution request.
- `RUNNING → SUCCEEDED` requires successful executor completion.
- `RUNNING → FAILED` records a deterministic failure outcome.
- `RUNNING → CANCELLED` requires an explicitly authorized cancellation operation.
- Terminal states MUST NOT silently transition back to `RUNNING`.
- Invalid transitions MUST be rejected rather than treated as successful no-ops.

The state machine is a domain invariant and MUST NOT be implemented only in an API router.

---

## 5. Actor and Principal Binding

A Principal is the authenticated caller. An Actor is the organizational entity executing the task.

They MUST remain distinct concepts.

Before execution:

1. Principal MUST be authenticated.
2. Principal MUST be explicitly bound to the requested Actor.
3. Actor MUST belong to the task's organization.
4. Actor MUST be active.
5. Actor MUST possess the capability required by the task type/operation.

A Principal/Actor mismatch MUST be denied.

---

## 6. Capability Contract

Task execution MUST require an explicit capability.

Canonical examples:

```text
 task.execute
 task.cancel
 task.retry
 task.read
```

Capability names MUST be stable strings.

Executor implementation details MUST NOT implicitly grant authority.

A task executor MUST never decide that a caller is authorized merely because it was invoked by an API route or because the Actor has a particular type.

---

## 7. Executor Selection

Executor selection MUST be deterministic.

The selection boundary is:

```text
Task.task_type / Actor.type
        ↓
TaskExecutorFactory
        ↓
Concrete TaskExecutor
```

The factory MUST NOT perform authorization itself.

The executor MUST NOT mutate authorization state.

The separation is:

```text
AuthorizationService → may this Actor execute?
TaskExecutorFactory  → which executor handles it?
TaskExecutor         → how is the task executed?
Task aggregate       → is the state transition valid?
```

---

## 8. Executor Result Contract

Every executor MUST return a structured execution result.

Minimum shape:

```text
ExecutionResult
- status: SUCCEEDED | FAILED
- task_id
- executor_type
- output_reference (optional)
- error_code (optional)
- metadata
```

Raw exceptions MUST NOT be exposed as the canonical API contract.

Sensitive credentials, provider tokens, private prompts, and secret payloads MUST NOT be persisted in execution metadata or audit records.

---

## 9. Failure Semantics

Failures MUST be explicit and observable.

The runtime MUST distinguish at least:

```text
AUTHORIZATION_DENIED
TASK_NOT_FOUND
ORGANIZATION_MISMATCH
INVALID_STATE_TRANSITION
EXECUTOR_NOT_AVAILABLE
EXECUTION_FAILED
EXECUTION_CONFLICT
RUNTIME_NOT_READY
```

A programming error MUST NOT be converted into a successful task result.

Broad exception handling MUST NOT silently return success, empty output, or a false-positive execution receipt.

---

## 10. Idempotency and Execution Receipts

Every execution request MUST carry a stable command/execution ID.

For the same organization and task:

```text
same execution_id + same request data
    → existing result MAY be returned

same execution_id + conflicting request data
    → EXECUTION_CONFLICT
```

The system MUST NOT execute the same accepted execution request twice merely because a client retries after a timeout.

An execution receipt MUST bind at minimum:

```text
execution_id
organization_id
task_id
actor_id
request fingerprint
status
created_at
completed_at where applicable
```

---

## 11. Transaction Boundary

The Unit of Work remains the transaction boundary for persistent state changes.

For an accepted execution request:

```text
authorize
  ↓
validate task state
  ↓
record execution acceptance
  ↓
execute / record deterministic executor result
  ↓
apply task state transition
  ↓
persist event/audit data
  ↓
commit
```

A failed transaction MUST NOT leave a task marked as successfully completed.

No partial task state, execution receipt, or event state is acceptable.

Where an external side effect cannot participate in the database transaction, the contract MUST represent that boundary explicitly rather than pretending the operation is atomic.

---

## 12. Audit and Events

A state-changing execution MUST produce an auditable event.

At minimum, the audit trail MUST establish:

```text
who      → principal / actor
where    → organization
what     → task / execution
executor → selected executor type
result   → success / failure / denial
when     → timestamp
why      → reason/error code where applicable
```

Events MUST remain organization-scoped and use the existing event envelope contract.

P3-14 MUST NOT introduce a parallel audit database merely for task execution.

---

## 13. API Boundary

The API layer is an adapter, not the execution engine.

An endpoint MUST:

- authenticate the Principal;
- establish organization context;
- invoke the canonical application/service boundary;
- return the structured execution result.

An endpoint MUST NOT contain the complete task execution state machine.

A second endpoint implementing the same execution semantics MUST NOT be introduced without an explicit compatibility/deprecation contract.

---

## 14. Runtime Readiness

Task execution MUST fail closed if the runtime is not ready.

A request MUST NOT execute against partially booted persistence or missing required infrastructure.

Readiness is distinct from liveness:

```text
liveness  → process is running
readiness → task execution is safe
```

---

## 15. Test Contract

P3-14 is incomplete until the following gates exist and pass:

```text
P3-14-01  Task organization identity is mandatory
P3-14-02  Principal → Actor binding is enforced
P3-14-03  Cross-organization task execution is denied
P3-14-04  Inactive Actor execution is denied
P3-14-05  Missing capability execution is denied
P3-14-06  Valid PENDING → RUNNING transition succeeds
P3-14-07  Invalid task transitions are rejected
P3-14-08  Executor selection is deterministic
P3-14-09  Successful execution produces a structured result
P3-14-10  Failed execution produces an explicit failure result
P3-14-11  Execution receipt is persisted
P3-14-12  Duplicate execution ID is idempotent
P3-14-13  Conflicting execution ID is rejected
P3-14-14  Execution event/audit data is persisted
P3-14-15  Transaction failure leaves no partial success state
P3-14-16  API delegates to the canonical execution boundary
P3-14-17  Runtime-not-ready execution fails closed
P3-14-18  Full regression suite remains green
```

Required invariant:

```text
Foundation + Phase 3 + P3-14 tests = 0 regressions
```

---

## 16. Security Invariants

The following are non-negotiable:

1. No implicit organization defaults.
2. No Principal/Actor substitution.
3. No cross-organization execution.
4. No capability bypass through executor type.
5. No hardcoded administrator bypass.
6. No successful result after an execution exception.
7. No duplicate execution caused by retry.
8. No secret material in task events, receipts, or logs.
9. No mutation while runtime readiness is false.
10. No alternate task execution path outside the canonical boundary.

---

## 17. Non-Goals

P3-14 does NOT implement:

- real OpenAI/Anthropic/Mistral/DeepSeek provider integration;
- prompt engineering or model selection policy;
- autonomous agent loops;
- GitHub automation;
- dashboard/UI redesign;
- distributed worker orchestration;
- Kubernetes deployment;
- distributed locks or consensus;
- billing or quotas;
- OAuth/OIDC;
- multi-region execution.

These require separate contracts.

---

## 18. Implementation Order

Implementation MUST proceed in this order:

1. Formalize Task execution state contract.
2. Add/verify organization-scoped Task identity.
3. Define execution command/receipt contract.
4. Implement canonical TaskExecutionService boundary.
5. Integrate Phase 3 authorization.
6. Implement deterministic executor selection.
7. Implement structured executor results and failure codes.
8. Persist execution receipts and events atomically.
9. Integrate API boundary.
10. Add all P3-14 acceptance tests.
11. Run complete regression suite.
12. Perform architecture/security audit before any merge beyond the contract commit.

No implementation step may bypass an earlier contract item.

---

## 19. Completion Criteria

P3-14 is complete only when:

- task execution has one canonical runtime boundary;
- organization scope is explicit and mandatory;
- Principal and Actor remain distinct and explicitly bound;
- authorization occurs before execution;
- task state transitions are domain-enforced;
- executor selection is deterministic;
- failures are explicit and fail closed;
- execution requests are idempotent;
- execution receipts and events are durable;
- transaction boundaries prevent partial persistent success;
- API routes delegate rather than duplicate execution logic;
- all P3-14 gates pass;
- all previous tests pass;
- no legacy authorization bypass is introduced.

**Contract status: READY FOR IMPLEMENTATION.**
