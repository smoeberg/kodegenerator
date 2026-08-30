# Security operations — Digital Organization Runtime (DOR)

This document describes **runtime secrets and security boundaries** as
implemented in the codebase. It is not a substitute for architecture contracts
in `docs/`.

## Required environment variables (production)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy database URL for persistence |
| `DOR_IDENTITY_DATABASE_URL` | Optional separate SQLAlchemy URL for persistent HTTP principals; defaults to `DATABASE_URL` in production |
| `DOR_JWT_SECRET_KEY` | Explicit JWT signing secret |
| `DOR_ADMIN_PASSWORD` | One-time bootstrap credential for the initial persistent admin |
| `DOR_AUTHORITY_SIGNING_KEY` | URL-safe base64 key (≥32 decoded bytes) shared by AI-3/AI-4 processes that exchange grants |
| `OPENAI_API_KEY` | Only if Implementation Agent provider is enabled |
| `DOR_IMPLEMENTATION_MODEL` | Model id for Implementation Agent |
| `DOR_IMPLEMENTATION_ALLOWED_RESOURCES` | Comma-separated allowlisted resources |

### Generate an authority signing key

```bash
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

If `DOR_AUTHORITY_SIGNING_KEY` is **absent**, DOR creates a **process-local
ephemeral key**. That is safe for single-process tests but **fails closed across
restarts** and is not a multi-process configuration.

### Rotation

- Rotating the signing key invalidates outstanding grants (expected).
- It must **not** wipe the execution replay ledger; replay identity is
  `execution_id`, not the HMAC key.

## Authority → execution boundary

```text
AuthorityDecision  (AI-3 policy outcome + HMAC provenance)
        │
        ▼
VerifiedAuthorityGrant  (short-lived, signed, bound claims)
        │
        ▼
ExecutionEngine  (rejects raw decisions; requires verified grant)
```

See `docs/phase4/P4_00D_SECURITY_REVIEW.md` and
`docs/phase4/P4_00D_INDEPENDENT_REVIEW.md`.

## Public HTTP surface

Canonical entrypoint: `api/main.py`.

Mounted with authentication (except health/auth):

- `control_plane`, `workflows`, `implementation_agent`

The former task, artifact, organization, actor, capability, intent, role,
workflow-template, and governance-gate routers were removed. Their ID-only
lookups did not derive tenant scope from the authenticated principal. The
canonical module inventory and retired path denylist live in
`api/api_surface.py`; API startup and regression tests fail if the mounted
router set drifts or a retired module/path is restored.

`api/endpoints/swarm_dashboard.py` remains an internal, unmounted component
with an isolated test contract. It is not part of the canonical public API.

## Persistent HTTP identity

Production authentication stores principals in `identity_principals`. The
bootstrap administrator is inserted only when absent; subsequent logins do not
replace its password hash. Each principal has a monotonically increasing
`credential_version`, embedded as `cv` in JWTs. Password rotation and account
disablement increment the version, immediately invalidating previously issued
tokens across all API instances.

The process-local `fake_users_db` alias remains solely for development and
legacy test fixtures. Production startup requires `DATABASE_URL` and never
uses that map as its identity authority. Apply Alembic migrations before
starting the canonical API.

### JWT signing-key rotation

Production may migrate from the single `DOR_JWT_SECRET_KEY` to a named HMAC
keyring. Configure `DOR_JWT_SIGNING_KEYS` as a JSON object and select the only
issuer key with `DOR_JWT_ACTIVE_KEY_ID`. Issued tokens contain that key ID in
the protected `kid` header. Verification selects only the named key: missing,
unknown, algorithm-mismatched, or revoked key IDs fail closed without trying
another secret.

Rotate without an authentication outage by adding a new key, switching the
active ID, retaining the previous verification key for at least the maximum
token lifetime, and then adding the previous ID to
`DOR_JWT_REVOKED_KEY_IDS`. The active key may never be revoked. All production
HMAC values must contain at least 32 characters. Deploy keyring changes
atomically to every API replica through the configured secret manager; never
store the JSON keyring in source control.

## Tenant isolation

Canonical Phase 3 paths use `establish_context` and
`get_for_organization(...)` queries. PostgreSQL additionally enables and
forces row-level security on the canonical runtime tables. Every runtime
transaction sets `dor.organization_id` with transaction-local `set_config`;
missing or mismatched context therefore returns no tenant rows and cannot
insert or update them. Connection-pool reuse cannot retain this setting.

The RLS boundary covers actors, role definitions and assignments, workflows,
projects, domain events, command and task-execution receipts, Pipeline state,
governed LLM calls, terminal side effects, and all durable Council tables.
Identity principals are global authentication records. Queue and execution
replay tables are protected by mandatory `organization_id` scope, composite
tenant keys, and RLS.

## Local secrets

Key material and salts must stay out of git (see `.gitignore`). Prefer
environment or secret stores over files in the working tree.

## Phase 6 sandbox

Process isolation (e.g. Bubblewrap) is an **environment** requirement where
enabled. Missing `bwrap` / user namespaces in CI is an infrastructure limit,
not an authority-bypass in AI-4. Since Fase 7 such environment limits are
governed by the controlled platform-skip manifest
(`ci/manifests/platform_skips.json`) — each former "environment error" is
either green on the correct runner or precisely skipped with an owner and a
reason — instead of blanket CI skips.

## Operational security runbooks

Fase 8 ships the operational runbooks for container and database security
hardening, key-material handling, restore-from-backup, and vendor switches in
[`docs/RUNBOOKS.md`](docs/RUNBOOKS.md) (R-03 container hardening, R-04
database hardening, R-05 restore, R-06/R-07/R-08 vendor switches). Staging
certification and rollback are operated via
[`ci/staging/reconcile_cli.py`](ci/staging/reconcile_cli.py).
