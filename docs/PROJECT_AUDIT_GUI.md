# Project Audit GUI

The Streamlit Project Audit page is a server-side adapter over the existing governed, read-only `ProjectAuditRuntime`. It does not add a browser-owned repository path and it does not turn an audit recommendation into execution authority.

## Trust boundary

The page restores the immutable onboarding intent from the API result stored in the authenticated Streamlit session and recalculates both `intent_id` and `content_fingerprint`. A mismatch fails closed.

The repository checkout is selected only from server-side configuration:

- `DOR_PROJECT_AUDIT_ORGANIZATION_ID`
- `DOR_PROJECT_AUDIT_REPOSITORY`
- `DOR_PROJECT_AUDIT_CHECKOUT_ROOT`

The configured organization and exact repository identity must match the onboarding intent. Wildcard repository identities are rejected.

The browser never supplies a filesystem path. The audit always runs against `HEAD` of the configured checkout, and the existing Git manifest builder rejects tracked working-tree drift before evidence is collected.

## Production checkout

The runtime image includes the Git executable, but `.git` is deliberately excluded from the application image build context. Production therefore requires an operator-managed Git checkout mounted into the dashboard container/process.

Use a dedicated checkout that:

1. contains the Git metadata required by `ProjectAuditRuntime`;
2. is clean at the intended revision;
3. is mounted read-only into the dashboard runtime;
4. contains only repository material intended for audit;
5. does not expose deployment `.env` files, credentials, SSH material, or unrelated host paths.

For example, an environment may bind a dedicated checkout to `/audit/repository:ro` and set `DOR_PROJECT_AUDIT_CHECKOUT_ROOT=/audit/repository`. The canonical `compose.yml` does not invent or auto-populate this checkout because repository acquisition and credentials are deployment-specific trust decisions.

## Semantics

Project Audit remains advisory and read-only. Its report is not PASS/FAIL and is not authoritative. `audit_only` onboarding intents stop after audit and remain ineligible for scaffold/delivery. Other purposes may use the report as downstream provenance, but execution still requires the normal governed authority boundary.
