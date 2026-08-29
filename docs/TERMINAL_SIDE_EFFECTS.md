# Terminal side-effect idempotency

Deployments and pull-request publication are external mutations. Phase 4 wraps
both executors in a shared durable receipt boundary backed by
`terminal_side_effects` from Alembic revision `013_terminal_side_effects`.

## Identity

Each operation is identified by:

```text
(organization_id, action, idempotency_key, request_fingerprint)
```

Use the immutable pipeline `task_id` as the idempotency key. Reusing that key
with changed repository, release, environment, target, patch or PR metadata is
rejected. Credentials and authority-grant objects are excluded from the
fingerprint and are never persisted.

## Two-worker behaviour

1. Worker A atomically inserts an `in_progress` receipt and receives a fencing
   token.
2. Worker B attempting the same task is rejected while A's lease is valid.
3. A performs the Docker build/push plus Compose deployment, or PR publication.
4. A can complete the receipt only with its current fencing token.
5. Later delivery of the same task replays the stored receipt without invoking
   Docker, Compose or GitHub again.

The test suite starts two workers against the same SQL database while the first
backend call is blocked. It proves exactly one deploy backend invocation—which
contains one image build/push and one deployment—and exactly one publisher
invocation.

## Recovery

```bash
export DATABASE_URL='postgresql+psycopg://dor:...@db/dor'
export DOR_SIDE_EFFECT_LEASE_SECONDS=1800
alembic upgrade head
```

Failed operations record their failure class and may be claimed again. If the
external operation returns successfully but receipt persistence fails, the
coordinator deliberately retains the active lease instead of marking the task
retryable. Operators must reconcile the external target before recovering an
expired receipt.

Docker image tags are derived from the checked-out commit, Compose `up` targets
that image, and release branches are deterministic. These external identities
must remain stable; changing them defeats recovery safety.

## Operational queries

- Alert on receipts still `in_progress` after their lease expiry.
- Compare deployment image/commit or GitHub head branch before lease recovery.
- Never delete a completed receipt while the corresponding pipeline can replay.
- Treat `SideEffectConflictError` and stale fencing tokens as incidents.
