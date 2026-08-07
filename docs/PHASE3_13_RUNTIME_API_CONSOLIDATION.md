# Phase 3.13 — Runtime/API Persistence Consolidation

## Objective

Establish one canonical runtime boundary for the public API:

`FastAPI -> DORRuntime -> infrastructure.persistence -> database`

The API must not depend on the removed `DORRuntimeDB`, `domain.role_definition`, or the legacy `DORDBAdapter` persistence path.

## Current boundary

P3-13 exposes only the canonical runtime surface needed for the Phase 3 workflow authority contract:

- `GET /health`
- authentication endpoints
- `GET /protected`
- `POST /workflows/`
- `GET /workflows/{workflow_id}`
- `POST /workflows/{workflow_id}/transition`

The legacy artifact, task, intent, capability, organization, role-definition, template and governance routers are deliberately not mounted while their persistence contracts still depend on the retired adapter layer. They are not silently presented as working APIs.

## Security invariants

1. Organization scope is explicit at every runtime resource boundary.
2. The authenticated principal is bound to the actor through `DORRuntime.establish_context`.
3. Cross-organization resource access fails closed.
4. Workflow transitions pass through `DORRuntime.execute_command` and `AuthorizationService`.
5. `RoleDefinition.organization_id` remains mandatory; no organization default is permitted.

## Exit criteria

Before merging P3-13 into `main`:

- `api.main.app` imports successfully with the required JWT secret configured.
- The API boundary test passes.
- Full pytest suite is green.
- `compileall` is green.
- Bandit is green.
- `pip-audit` is a blocking CI gate.
- CI only targets `main` for pull requests and the active P3-13 development branch for push validation.
- No mounted API router imports or calls the retired persistence adapter.
- Legacy routers are either migrated to the canonical runtime or removed in a subsequent explicitly scoped phase; they must not be re-mounted by accident.

## Non-goals

Actual LLM provider integration remains a later phase. `AIClient.generate_response()` must continue to fail explicitly rather than return fabricated model output.
