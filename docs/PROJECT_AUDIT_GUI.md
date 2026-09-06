# Project Audit GUI

The Streamlit Project Audit page is a server-side adapter over the existing governed, read-only `ProjectAuditRuntime`. It does not add a browser-owned repository path and it does not turn an audit recommendation into execution authority.

## Trust boundary

The page restores the immutable onboarding intent from the API result stored in the authenticated Streamlit session and recalculates both `intent_id` and `content_fingerprint`. A mismatch fails closed.

Repository discovery is server-owned. The preferred configuration uses:

- `DOR_PROJECT_AUDIT_CHECKOUTS_ROOT`
- `DOR_PROJECT_AUDIT_CHECKOUT_CATALOG`

The catalog is versioned JSON with exact organization/repository identities and a relative checkout path under the trusted root:

```json
{
  "version": 1,
  "repositories": [
    {
      "organization_id": "dor-org",
      "repository": "repository:smoeberg/kodegenerator",
      "checkout": "kodegenerator"
    }
  ]
}
```

Catalog entries reject authority wildcards, duplicate organization/repository identities, absolute checkout paths, `..` traversal, missing directories, and symlink resolution outside the trusted checkout root. Partial catalog configuration also fails closed.

Onboarding uses the catalog as a governed repository picker scoped to the authenticated organization. Project Audit does not trust that UI selection as execution authority; it resolves the exact organization + repository identity against the server-owned catalog again before accessing the checkout.

The browser never supplies a filesystem path. The audit always runs against `HEAD` of the resolved checkout, and the existing Git manifest builder rejects tracked working-tree drift before evidence is collected.

## Production checkout catalog

The runtime image includes the Git executable, but `.git` is deliberately excluded from the application image build context. Production therefore requires operator-managed Git checkouts mounted into the dashboard container/process.

Use dedicated checkouts that:

1. contain the Git metadata required by `ProjectAuditRuntime`;
2. are clean at the intended revision;
3. are mounted read-only into the dashboard runtime;
4. contain only repository material intended for audit;
5. do not expose deployment `.env` files, credentials, SSH material, or unrelated host paths.

An example catalog is available at `docs/project-audit-checkouts.example.json`.

For Docker Compose, set the host paths:

```text
DOR_PROJECT_AUDIT_CHECKOUTS_HOST_ROOT=/srv/dor/audit-checkouts
DOR_PROJECT_AUDIT_CHECKOUT_CATALOG_HOST_FILE=/etc/dor/project-audit-checkouts.json
```

Then start with the explicit Project Audit override:

```bash
docker compose -f compose.yml -f compose.project-audit.yml up -d
```

The override mounts the host checkout root at `/audit/checkouts:ro`, mounts the catalog at `/audit/catalog.json:ro`, and sets the two server-side catalog environment variables inside the dashboard service. The canonical `compose.yml` still does not auto-mount a host source tree or credentials.

For non-Compose deployments, mount equivalent read-only paths and set `DOR_PROJECT_AUDIT_CHECKOUTS_ROOT` and `DOR_PROJECT_AUDIT_CHECKOUT_CATALOG` directly in the dashboard process.

## Legacy single-checkout compatibility

The original v1 configuration remains supported when catalog mode is absent:

- `DOR_PROJECT_AUDIT_ORGANIZATION_ID`
- `DOR_PROJECT_AUDIT_REPOSITORY`
- `DOR_PROJECT_AUDIT_CHECKOUT_ROOT`

If either catalog variable is present, both are required and catalog mode takes precedence. The implementation never silently falls back to the legacy binding from a partially configured catalog.

## Semantics

Project Audit remains advisory and read-only. Its report is not PASS/FAIL and is not authoritative. `audit_only` onboarding intents stop after audit and remain ineligible for scaffold/delivery. Other purposes may use the report as downstream provenance, but execution still requires the normal governed authority boundary.
