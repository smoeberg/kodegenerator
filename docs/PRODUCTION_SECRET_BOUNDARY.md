# Production Secret Boundary

This contract defines how the canonical DOR production runtime receives secret
material. It is intentionally narrower than general host or container security:
it prevents repository configuration, Compose interpolation and image metadata
from becoming the production secret store.

## Invariant

A production secret value MUST NOT be:

- committed to the repository;
- stored in `.env` or `.env.example`;
- interpolated as a value into the canonical `compose.yml` service environment;
- baked into the runtime image, build arguments, labels or build metadata;
- included in validation errors or normal logs.

The canonical Compose stack receives only host **paths** to operator-managed
secret files. Docker Compose mounts those files beneath `/run/secrets`. DOR
then materializes allowlisted `*_FILE` inputs only after the runtime process
starts.

## Canonical Compose secrets

`compose.yml` requires host paths for:

- PostgreSQL password;
- MinIO root/access identity and password;
- JWT signing keyring;
- authority signing key;
- encryption key;
- bootstrap administrator password;
- worker credential.

`.env.example` documents those host paths, not the secret values.

PostgreSQL and MinIO consume their native file-backed secret variables. DOR
runtime roles use `POSTGRES_PASSWORD_FILE`, `AWS_ACCESS_KEY_ID_FILE`,
`AWS_SECRET_ACCESS_KEY_FILE`, `DOR_JWT_SIGNING_KEYS_FILE`,
`DOR_AUTHORITY_SIGNING_KEY_FILE`, `DOR_ENCRYPTION_KEY_FILE`, and the
role-specific admin/worker file variables.

The runtime constructs its three canonical SQLAlchemy PostgreSQL URLs only
after the PostgreSQL password file has been read. The password is URL-encoded
before the URLs are constructed.

## Runtime materialization

`services.runtime_secrets.materialize_runtime_secrets` is the authority for
file-backed materialization. In `DOR_ENV=production` it fails closed when:

- an allowlisted secret is inherited directly as `NAME=value`;
- both `NAME` and `NAME_FILE` are present;
- a secret path is relative, missing, unreadable, non-regular or a symlink;
- a secret file is empty, larger than the bounded maximum, or invalid UTF-8.

Errors identify the configuration key but never include the secret payload.
The container entrypoint loads secrets before validation and before executing
the canonical API, dashboard, migration or worker command.

Development and demo environments retain direct-environment compatibility for
local/test workflows. This exception MUST NOT be used to weaken the production
boundary.

## External secret providers

A production platform may use Vault, cloud secret managers, Kubernetes or
another approved provider instead of Docker Compose secrets. The equivalent
boundary is:

```text
approved secret provider
        -> file mounted into the runtime namespace
        -> NAME_FILE=/absolute/path
        -> DOR runtime materialization
```

Platform-specific deployments may use the same mechanism for optional provider
credentials such as `OPENAI_API_KEY_FILE` and `REDMINE_API_KEY_FILE`.

## Rotation and least privilege

Rotation replaces the provider-managed secret and restarts/redeploys the
processes that consume it. Existing JWT keyring rotation and authority-grant
invalidation semantics remain unchanged.

Role-specific credentials are mounted only where needed in the canonical
Compose stack: the administrator password is limited to API/dashboard roles,
and the worker credential to migrate/worker roles. Shared persistence,
artifact, JWT, authority and encryption material follows the existing runtime
role contract.

## Non-goals

This contract does not claim that a secret disappears from process memory after
materialization, nor does it protect a container from a fully privileged host
administrator. Application libraries still receive required credentials in the
runtime process environment. The protected boundary is the deployment control
plane: repository files, Compose configuration, image metadata and logs must
not contain production secret values.

## Regression evidence

Tests must prove at least:

- direct production secret values are rejected without disclosure;
- file-backed secrets materialize successfully;
- ambiguous direct + file sources fail closed;
- unsafe file paths/types/sizes fail closed;
- database URLs are derived only after password materialization;
- canonical Compose contains file-backed secret mounts instead of direct secret
  interpolation;
- `.env.example` contains secret paths, not secret values.
