# Security operations — Digital Organization Runtime (DOR)

This document describes **runtime secrets and security boundaries** as
implemented in the codebase. It is not a substitute for architecture contracts
in `docs/`.

## Production secret boundary

The canonical production installation does **not** use `.env` or Compose
environment interpolation as the secret-value store. `compose.yml` receives
operator-managed secret **file paths**, mounts those files under `/run/secrets`,
and DOR materializes allowlisted `*_FILE` inputs only after the runtime process
starts.

In `DOR_ENV=production`, inheriting an allowlisted secret directly as
`NAME=value` fails closed. A configuration may not provide both `NAME` and
`NAME_FILE`. Secret-file reads are bounded and reject relative paths,
non-regular files, symlinks, empty payloads and invalid UTF-8 without including
the payload in errors.

Canonical production inputs include:

| Secret | Canonical source |
|--------|------------------|
| PostgreSQL password | `POSTGRES_PASSWORD_FILE` |
| Artifact-store access identity | `AWS_ACCESS_KEY_ID_FILE` |
| Artifact-store secret | `AWS_SECRET_ACCESS_KEY_FILE` |
| JWT signing keyring | `DOR_JWT_SIGNING_KEYS_FILE` |
| Authority signing key | `DOR_AUTHORITY_SIGNING_KEY_FILE` |
| Encryption key | `DOR_ENCRYPTION_KEY_FILE` |
| Bootstrap admin password | `DOR_ADMIN_PASSWORD_FILE` |
| Worker credential | `DOR_WORKER_CREDENTIAL_FILE` |

The canonical SQLAlchemy database URLs are constructed inside the runtime after
the PostgreSQL password file is materialized. Non-Compose production platforms
may instead mount a complete URL and expose `DATABASE_URL_FILE`,
`DOR_IDENTITY_DATABASE_URL_FILE`, and `DOR_PIPELINE_DATABASE_URL_FILE`.
Optional provider credentials use the same mechanism, for example
`OPENAI_API_KEY_FILE` and `REDMINE_API_KEY_FILE`.

The complete normative contract, rotation model and non-goals are in
[`docs/PRODUCTION_SECRET_BOUNDARY.md`](docs/PRODUCTION_SECRET_BOUNDARY.md).
Development and demo environments retain direct-environment compatibility; that
compatibility is not a production bypass.

### Generate an authority signing key

```bash
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

If `DOR_AUTHORITY_SIGNING_KEY` is **absent** in development/test contexts, DOR
may create a **process-local ephemeral key**. That is safe for single-process
tests but **fails closed across restarts** and is not a production or
multi-process configuration.

### Rotation

- Rotating the authority signing key invalidates outstanding grants (expected).
- It must **not** wipe the execution replay ledger; replay identity is
  `execution_id`, not the HMAC key.
- Replace provider-managed secret files atomically and restart/redeploy every
  process that consumes the rotated material.

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
legacy test fixtures. Production startup requires the canonical PostgreSQL
wiring and never uses that map as its identity authority. Apply Alembic
migrations before starting the canonical API.

### JWT signing-key rotation

Production uses a named HMAC keyring. Configure the keyring through
`DOR_JWT_SIGNING_KEYS_FILE` and select the issuer key with
`DOR_JWT_ACTIVE_KEY_ID`. Issued tokens contain that key ID in the protected
`kid` header. Verification selects only the named key: missing, unknown,
algorithm-mismatched, or revoked key IDs fail closed without trying another
secret.

Rotate without an authentication outage by adding a new key, switching the
active ID, retaining the previous verification key for at least the maximum
token lifetime, and then adding the previous ID to
`DOR_JWT_REVOKED_KEY_IDS`. The active key may never be revoked. All production
HMAC values must contain at least 32 characters. Deploy keyring changes
atomically to every API replica through the approved secret provider; never
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

Key material and salts must stay out of git (see `.gitignore`). `.env` may hold
non-secret configuration and host paths to secret files, but production secret
values belong in the approved operator/platform secret provider.

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
