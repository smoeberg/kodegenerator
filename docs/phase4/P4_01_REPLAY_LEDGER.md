# P4-01 — Durable Authority & Replay Ledger

**Status:** Implemented in code (state machine + SQLAlchemy backend); see open
hardenings (migration, append-only abandon, lease expiry PR).

## Invariant

For a given `execution_id`, the adapter may perform at most **one successful**
side-effecting invocation cluster-wide when a shared durable ledger is used.

`execution_id` is the SHA-256 of request security fields + policy binding
(`phase4/execution/models.py`). **`grant_id` is not** part of the hash.

## State machine

```text
(empty | failed | abandoned) ──claim──► pending
    pending ──complete(succeeded)──► succeeded   (lock → REPLAYED)
    pending ──complete(failed)─────► failed      (retryable)
    pending ──abandon──────────────► abandoned   (retryable; row retained)
    pending ──concurrent claim─────► IN_FLIGHT   (fail-closed)
```

Lease expiry (when enabled) allows reclaim of **expired** pending after worker
crash (RA-3). See PR for lease column when merged.

## Modules

| Module | Role |
|--------|------|
| `phase4/execution/replay_ledger.py` | Port + `InMemoryReplayLedger` |
| `phase4/execution/durable_ledger.py` | `SqlAlchemyReplayLedger` + ORM model |
| `phase4/execution/engine.py` | Claim after grant verify/binds |

## Explicit non-claims

- Does not replace Phase 6 sandbox.
- Does not replace HMAC grant authenticity (P4-00D).
- Does not make adapters idempotent at the external system; defense in depth remains.
- Signing-key rotation does not clear the ledger.
