# P4-01 — Durable Authority & Replay Ledger

| Metadata | Value |
| --- | --- |
| Status | Reference implementation complete (in-process); durable backend port defined, not yet wired |
| Phase | 4 |
| Gate | P4-01 |
| Predecessor | P4-00D (#43, closed) — HMAC grant authenticity |
| Residual risks closed | RA-1 restart, RA-2 multi-worker, RA-3 crash-during-adapter, RA-4 cross-node replay |

## 1. Purpose

P4-00D secures the **authenticity** of the AI-3 → AI-4 grant (HMAC signature,
exact binding, lifetime). P4-01 secures **single execution over time and across
processes** for a genuine, bound grant:

> **Invariant:** For a given `execution_id` an adapter may run at most ONE
> successful side-effecting invocation cluster-wide.

P4-00D and P4-01 are complementary, not substitutes:

| Layer | Protects against |
| --- | --- |
| P4-00D HMAC + binds + TTL | Forgery, tampering, raw decision, expired grant |
| Process-local `_results` (pre-P4-01) | In-process repetition only |
| **P4-01 durable ledger** | Restart, multi-worker, crash-window, cross-node replay of a *genuine* grant |

## 2. Deduplication key

The deduplication key is `execution_id` (SHA-256 of request fields + the policy
binding), **not** `grant_id`.

- A fresh re-issued genuine grant for the same policy binding → same
  `execution_id` → **REPLAYED**.
- A new `policy_version` → new `execution_id` → **intentional new execution**
  (a policy change is a new decision; this is correct and is *not* a ledger
  concern).

`grant_id` is stored on the ledger record for audit only. It MUST NOT be hashed
into `execution_id`: doing so would break idempotent re-evaluation under a
legitimate re-issued grant.

## 3. Attack matrix covered

| ID | Attack | P4-01 control |
| --- | --- | --- |
| RA-1 | Process restart + same genuine grant (within TTL) | Durable completed-set shared across engine instances |
| RA-2 | Two workers, same request | Shared ledger + atomic claim |
| RA-3 | Crash during adapter call (at-least-once) | Atomic `pending` claim before adapter invocation |
| RA-4 | Leaked genuine grant used on a second node sharing the signing key | Cluster-wide dedup on `execution_id` |

## 4. Pending-claim policy

When a second caller finds an in-flight (`pending`) execution for the same
`execution_id`, the behaviour is **policy-driven**:

| `PendingClaimOutcome` | Behaviour | Use when |
| --- | --- | --- |
| `REJECT` (default) | Fail-closed: `REJECTED`, no wait, no adapter call | Default; safest, never deadlocks |
| `WAIT` | Block until the in-flight execution commits, then return the same terminal result as `REPLAYED` | Adapters known slow or naturally idempotent |

This mirrors the project's policy-driven verification model (Phase 4 §7).

## 5. Contract

### `ExecutionLedger` port

A durable backend implements:

```text
claim(execution_id, *, request_id, grant_id, policy_id, policy_version, started_at)
    -> (ACQUIRED, None)           # caller owns the execution; run the adapter
    -> (REPLAYED, terminal_record) # a terminal record already exists; replay
    -> (PENDING, in_flight_record) # an execution is in flight; apply policy

complete(execution_id, *, status, adapter_id, outcome_fingerprint, completed_at, error)
    # only the owning pending record may transition to terminal

get(execution_id) -> terminal_record | None
wait_for_terminal(execution_id, *, timeout) -> terminal_record | None
```

Requirements:

- `claim` is atomic: inserting `pending` for an `execution_id` that already has
  a record returns `REPLAYED` (terminal) or `PENDING` (in-flight); it never
  creates a second pending record.
- A terminal record is **never** mutated.
- The same store serves all AI-4 processes in the signing domain.
- The store is crash-safe (disk/DB, not process memory).
- **Signing-key rotation does not reset the ledger** (rotation ≠ replay reset).

### Execute algorithm (after `grant.verify` + binds + ALLOW check)

```text
1. execution_id = execution_id_for(request, decision)
2. (claim, existing) = ledger.claim(execution_id, ...)
3. if REPLAYED -> return REPLAYED (cached terminal result)
4. if PENDING   -> policy: REJECT -> REJECTED; WAIT -> wait then REPLAYED
5. ACQUIRED     -> run adapter ONCE
6. ledger.complete(execution_id, terminal status)
7. return terminal result
```

### `LedgerRecord`

```text
execution_id            # PK
status                  # pending -> succeeded | failed
request_id, grant_id    # audit (grant_id not in hash)
authority_policy_id
authority_policy_version
started_at / completed_at
adapter_id
outcome_fingerprint     # optional
error
```

`rejected` is never ledgered: a rejected request performs no side effect and
no adapter invocation.

## 6. Reference implementation

`phase4/execution/ledger.py` provides:

- `ExecutionLedger` (Protocol port)
- `InProcessLedger` — thread-safe reference that outlives any single
  `ExecutionEngine` and can be shared between engines to model multi-worker /
  cross-node replay.
- `ReplayPolicy` / `PendingClaimOutcome`
- `LedgerRecord`, `ClaimResult`

`ExecutionEngine` accepts an optional `ledger` and `replay_policy`. **Without a
ledger the legacy in-memory replay store is preserved** (backwards compatible).

A real durable backend (DB / queue) implements the same `ExecutionLedger`
protocol with disk-backed persistence. That wiring is the next P4-01 slice and
is **not** claimed by this reference implementation.

## 7. Residual risks (explicitly NOT claimed by P4-01)

1. **AI-3 re-issue without new business intent.** A `policy_version` bump
   legitimately produces a new `execution_id`. Preventing an attacker from
   provoking a re-issue without new business intent is an AI-3 / authority
   contract concern, not the ledger's.
2. **Adapter idempotency from the outside.** Adapters SHOULD still be
   idempotent (defense in depth). The ledger guarantees at-most-one successful
   side-effecting invocation per `execution_id`; it does not make arbitrary
   business APIs idempotent.
3. **`idempotency_key` confusion.** `execution_id` hashes `idempotency_key`.
   Many keys for the same business action → many executions. This is the
   current API/product contract and is intentionally preserved; the ledger
   documents rather than "fixes" it.
4. **Untrusted in-process code.** Outside the in-process HMAC contract; must
   be isolated by the Phase 6 sandbox.
5. **Crash-safe persistence.** `InProcessLedger` is durable *relative to the
   engine* (survives engine restart, shares across workers) but not durable
   *across process loss*. Disk/DB-backed persistence is the next slice.

## 8. Acceptance

The adversarial contract suite `tests/phase4/p4_01/test_durable_replay_ledger.py`
proves:

- RA-1/RA-2: a second genuine execution (restart / second worker) is REPLAYED
  with **one** adapter call total.
- RA-3: a concurrent caller on an in-flight execution is REJECTED by default
  (fail-closed) or REPLAYED after the in-flight completion under `WAIT` policy.
- RA-4: a leaked genuine grant on a second node sharing the ledger is deduplicated.
- Re-issued grant (new `grant_id`, same binding) replays.
- New `policy_version` is a new `execution_id` (intentional new execution).
- Signing-key rotation does not reset the ledger.
- A failed execution is cached and not retried.
- Pre-P4-01 baseline: without a ledger a restart re-runs the adapter
  (documented negative control proving the attack exists).
