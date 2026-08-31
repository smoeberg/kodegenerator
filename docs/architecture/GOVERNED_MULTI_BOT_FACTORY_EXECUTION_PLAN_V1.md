# Governed Multi-Bot Factory — Repository Execution Plan v1

```yaml
status: proposed
version: 1.0.0
repository: smoeberg/kodegenerator
base_commit: 1f4e1409e1a3dd9204f109c2fb1a8342258ba018
base_alembic_head: 017_queue_replay_tenant_scope
architecture: docs/architecture/GOVERNED_MULTI_BOT_FACTORY_V1.md
contracts: docs/contracts/MULTI_BOT_FACTORY_CONTRACTS_V1.md
owner: human
approval_required: true
```

## 1. Purpose and completion rule

This is the implementation authority for the governed multi-bot extension. It
maps every new contract to the current DOR repository and deliberately contains
no copy/paste implementation stubs or unresolved placeholders. A phase is complete only
when its migrations, production code, API contract where applicable, tests,
documentation, repository-state validation, and merge gate pass together.

This plan does not claim that runtime features are implemented. The existing
architecture and JSON schemas are the approved target only after human signoff.

## 2. Verified repository baseline

| Boundary | Canonical implementation at the plan base |
| --- | --- |
| Agent declaration | `phase4/agent_registry/models.py`, `registry.py` |
| Council roles and turns | `phase4/council/roles.py` |
| Council orchestration | `phase4/council/orchestrator.py` |
| Council persistence | `phase4/council/store.py`, `persistence_models.py` |
| Verification selection | `phase4/verification/selector.py` |
| Governed LLM | `services/governed_llm.py`, `services/llm_adapters.py` |
| Authority | `phase4/authority/` and `runtime/authority.py` |
| Task execution | `domain/task_execution.py` |
| AI-4 execution/replay | `phase4/execution/`, durable replay ledger |
| Worker queue | `infrastructure/runtime/queue.py` |
| Terminal effects | `services/side_effects.py`, SQLAlchemy side-effect store |
| Git/PR | `services/git_pr_publisher.py` |
| Tenant database context | `infrastructure/persistence/database.py` |
| HTTP tenant membership | `DORRuntime.establish_context()` |
| API inventory | `api/api_surface.py`, `api/main.py` |
| Migration chain | root `alembic/versions/`, head `017_queue_replay_tenant_scope` |

The AI-1 `AgentRegistry` is currently an in-memory reference implementation.
It remains the canonical declaration/identity contract in this project. The
tenant-owned Bot Catalog introduced below references `AgentIdentity`; it does
not turn AI-1 into a credential, quota, provider, or authorization service.

## 3. Non-negotiable implementation rules

1. Do not add another top-level `repositories/`, queue, authority engine, agent
   registry, Git publisher, migration hierarchy, or task-execution runtime.
2. Do not add provider or brand enums. Adapter type and brand are validated
   configuration strings. Adapter factories may support an explicit set.
3. Role display names are user-defined. `protocol_function` is a fixed runtime
   vocabulary and never names a bot or provider.
4. HTTP request models never trust tenant ownership. Endpoints call
   `DORRuntime.establish_context()` before a tenant repository is opened.
5. Persist `secret_reference`; never resolve, return, log, prompt, fingerprint,
   or persist the credential behind that reference.
6. Use timezone-aware UTC domain values and `DateTime(timezone=True)` columns.
7. Configuration records are immutable by version. A change appends a version;
   it does not rewrite evidence used by an active session.
8. Runtime assignment and evidence records are append-only.
9. Content fingerprints include every field that can change behavior and omit
   random IDs and mutable operational timestamps.
10. Queue claims and execution-ledger claims are created only by their existing
    canonical stores. A service cannot invent a lease or fencing token.
11. External branch push, integration push, and PR publication use
    `SideEffectCoordinator` with separate action names and idempotency keys.
12. No semantic evaluator can override a deterministic hard failure.
13. No fallback or substitution is silent. It is a separate, persisted
    selection decision and assignment linked to the superseded assignment.
14. Every new tenant table has composite tenant identity, explicit query scope,
    PostgreSQL RLS enable/force policy, and cross-tenant tests.
15. SQLite tests must retain explicit organization predicates; PostgreSQL RLS
    is defense in depth, not the only isolation control.

## 4. Canonical domain placement

### 4.1 Agent and bot configuration

Keep existing AI-1 models unchanged except for exports required by adapters.
Add:

| File | Owns |
| --- | --- |
| `phase4/agent_registry/bot_profiles.py` | Immutable `ProviderConnection`, `ModelDeployment`, `BotProfile` domain values and canonical fingerprints |
| `infrastructure/persistence/bot_catalog_models.py` | SQLAlchemy rows for those values |
| `infrastructure/persistence/bot_catalog_store.py` | Synchronous tenant-scoped store |

`BotProfile.agent_identity` stores the 64-character value produced by existing
`AgentIdentity`. Capability names must be a subset of the active AgentRecord's
declarations. A Bot Catalog profile cannot grant a new capability.

### 4.2 Roles, templates, and allocation

The existing `domain.RoleDefinitionModel` is an organizational RBAC role and is
not reused for Council choreography. Avoid the name collision by using explicit
Council names:

| File | Owns |
| --- | --- |
| `phase4/council/configuration.py` | `CouncilRoleDefinition`, `ProtocolFunction`, `CouncilTemplate`, `TemplateStage`, `RoleAllocationPool`, `IndependenceLevel`, `AutonomyLevel` |
| `infrastructure/persistence/council_configuration_models.py` | Versioned SQLAlchemy configuration rows |
| `infrastructure/persistence/council_configuration_store.py` | Tenant-scoped configuration store and validation |

Protocol functions are limited to:

- `conversation_owner`
- `proposer`
- `reviewer`
- `verifier`
- `implementer`
- `candidate_evaluator`
- `integrator`

These are flow semantics. Role names, purposes, prompts, schemas, rubrics, and
eligible bots remain human-configurable.

### 4.3 Selection and assignment

Keep `VerifierSelector` backward compatible. Add the allocation-aware boundary:

| File | Owns |
| --- | --- |
| `phase4/verification/allocation_selector.py` | Selection request, exclusion reasons, score components, deterministic ranking, blocked/selected decisions |
| `phase4/verification/assignment.py` | Frozen assignment and substitution linkage |
| `infrastructure/persistence/selection_models.py` | Selection/assignment rows |
| `infrastructure/persistence/selection_store.py` | Immutable decision and assignment store |

`VerifierSelector` may delegate to the new selector only when an allocation is
provided. Existing callers and deterministic verifier selection remain valid.

### 4.4 Evaluation and learning

| File | Owns |
| --- | --- |
| `phase4/verification/evaluation.py` | Rubrics, checks, evaluation records, independence validation |
| `phase4/verification/evaluation_coordinator.py` | Deterministic-before-semantic orchestration |
| `phase4/adaptation/performance.py` | Event-based observation and snapshot domain values |
| `infrastructure/persistence/evaluation_models.py` | Rubric, record, observation, snapshot rows |
| `infrastructure/persistence/evaluation_store.py` | Append-only tenant store and snapshot reads |
| `services/local_evaluator.py` | Adapter from a selected local/OpenAI-compatible provider to governed LLM evaluation requests |

LibreChat is configured as a provider connection using the existing
OpenAI-compatible adapter behavior. No domain model or role contains the word
LibreChat. The evaluator call still passes through `GovernedLLMRuntime` and its
durable replay store.

### 4.5 Factory work, candidates, and integration

| File | Owns |
| --- | --- |
| `domain/factory_work.py` | Work package configuration, execution mode, write scope, candidate and candidate-selection values |
| `execution/factory_task_synthesizer.py` | Approved contracts to dependency DAG/work packages |
| `infrastructure/persistence/factory_models.py` | Work package, candidate, candidate-selection, integration rows |
| `infrastructure/persistence/factory_store.py` | Tenant/OCC transitions and immutable delivery writes |
| `services/factory_scheduler.py` | Publish ready package IDs to existing `DatabaseQueue` |
| `services/factory_workspace.py` | Exact-base isolated worktrees and candidate branch lifecycle |
| `services/integration_controller.py` | Authority-bound candidate integration and reconciliation |

Do not place another `WorkPackage` in both `domain/task_execution.py` and
`phase4/execution`. `domain.factory_work` owns the package; it is translated to
the existing `TaskExecutionRequest` and `phase4.execution.ExecutionRequest` at
the relevant governed boundaries.

## 5. Database and migration contract

All new migrations form one linear chain from revision 017.

### 5.1 Revision 018 — bot catalog

File: `alembic/versions/018_bot_catalog.py`

| Table | Primary/unique identity | Required content |
| --- | --- | --- |
| `bot_provider_connections` | `(organization_id, connection_id, version)` | brand, adapter type, endpoint, secret reference, region, data boundary, concurrency limit, enabled, timestamps |
| `bot_model_deployments` | `(organization_id, deployment_id, revision)` | exact composite connection-version FK, model ID/family, token limits, structured-output flag, tools JSON, status, timestamps |
| `bot_profiles` | `(organization_id, bot_profile_id, version)` | agent identity, exact composite deployment-revision FK, display name, prompt version, capability/tool JSON, policy JSON, concurrency, enabled, fingerprint, timestamps |

Constraints:

- one immutable row per composite version identity;
- profile fingerprint length 64;
- no cascade from connection/deployment to audit-bearing profiles;
- active referenced records cannot be physically deleted, only disabled.

### 5.2 Revision 019 — Council configuration

File: `alembic/versions/019_council_configuration.py`

| Table | Identity | Required content |
| --- | --- | --- |
| `council_role_configurations` | `(organization_id, role_id, version)` | name, purpose, protocol function, capabilities, schema/rubric refs, verification flag, enabled, fingerprint |
| `council_templates` | `(organization_id, template_id, version)` | name, ordered stages JSON, approver, enabled, fingerprint |
| `council_role_allocations` | `(organization_id, allocation_id, version)` | role/version, independence/autonomy policy, constraints, approver, fingerprint |
| `council_role_allocation_members` | allocation composite FK + profile ID | preference rank, explicit fallback rank or null |

Constraints:

- every allocation member references a profile in the same organization;
- every template stage references role versions in the same organization;
- minimum assignments cannot exceed maximum assignments;
- one enabled allocation version per `(organization_id, role_id)`.

### 5.3 Revision 020 — selection and assignment

File: `alembic/versions/020_bot_selection_assignments.py`

| Table | Identity | Required content |
| --- | --- | --- |
| `bot_selection_decisions` | `(organization_id, decision_id)` | request/allocation/repository/policy/performance fingerprints, candidates/exclusions/scores JSON, selected snapshot, status, rationale, created time |
| `bot_session_assignments` | `(organization_id, assignment_id)` | session/task/role, complete selected profile/deployment/connection/model/prompt snapshot, input/base SHA, decision fingerprint, expiry, supersedes ID |

Constraints:

- one selected decision for one request fingerprint and policy snapshot;
- selected profile must appear in the bound allocation-member snapshot;
- one active assignment per `(organization_id, scope_id, role_id)`;
- substitution is a new row and cannot update the original;
- assignment links to Council session where the scope is a Council session.

### 5.4 Revision 021 — evaluation and performance

File: `alembic/versions/021_bot_evaluation_performance.py`

| Table | Identity | Required content |
| --- | --- | --- |
| `evaluation_rubrics` | `(organization_id, rubric_id, version)` | subject classes, criteria/checks/hard failures JSON, threshold, independence policy, fingerprint |
| `evaluation_records` | `(organization_id, evaluation_id)` | producer/evaluator assignments, subject/rubric/base SHA, checks/semantic evidence/hard failures, outcome, confidence, score, provenance, fingerprint |
| `bot_performance_observations` | `(organization_id, observation_id)` | profile/role/task context, event type/value, model/prompt/rubric versions, evidence, source, supersedes, event time |
| `bot_performance_snapshots` | `(organization_id, snapshot_id)` | context dimensions, sample/window, definitions/values, confidence/decay/exclusions, ledger position, fingerprint |

Corrections append an observation with `supersedes_observation_id`. Update and
delete operations are not exposed by the store. Snapshot generation records the
highest included ledger position and cannot include later observations.

### 5.5 Revision 022 — work packages and candidates

File: `alembic/versions/022_factory_work_candidates.py`

| Table | Identity | Required content |
| --- | --- | --- |
| `factory_work_packages` | `(organization_id, work_package_id)` | workflow/task, requirements/architecture/contracts/base SHA, dependencies, criteria/checks/write scope, mode/count/allocation/policy, budgets, idempotency key, fingerprint, status, OCC version |
| `factory_candidate_deliveries` | `(organization_id, candidate_id)` | package/execution/assignment, base/branch/head/commits, patch/path data, attestations, status, fingerprint, delivered time |
| `factory_candidate_selections` | `(organization_id, selection_id)` | logical task/package, candidate list, rubric/evidence/exclusions, winner or no-winner, evaluator assignment, authority provenance, fingerprint |

Constraints:

- unique package idempotency key per organization;
- unique candidate `(organization_id, execution_id, head_sha)`;
- at most one accepted winner for `(organization_id, logical_task_id,
  work_package_fingerprint)` using a partial unique index in PostgreSQL and an
  equivalent transactional check in SQLite tests;
- candidate head and fingerprint are immutable after delivery.

### 5.6 Revision 023 — integration

File: `alembic/versions/023_factory_integration.py`

| Table | Identity | Required content |
| --- | --- | --- |
| `factory_integration_plans` | `(organization_id, plan_id)` | workflow/repository/base SHA, ordered candidate/head pairs, dependency/compatibility evidence, integration branch, idempotency, required authority action, fingerprint, status, OCC version |
| `factory_integration_receipts` | `(organization_id, receipt_id)` | plan/fingerprint, side-effect fencing reference, integration branch/head, outcome/conflicts, suite attestation, side-effect receipt reference, status, time |

Constraints:

- one plan per `(organization_id, workflow_id, plan_fingerprint)`;
- one successful receipt per plan fingerprint;
- receipt result must match the completed `factory.integrate` side-effect
  receipt; credentials and authority grants are never copied into either row.

### 5.7 RLS and downgrade requirements

Every table above receives the same PostgreSQL policy shape as revision 017:

```text
organization_id = nullif(current_setting('dor.organization_id', true), '')
```

Migration tests must prove `ENABLE` and `FORCE ROW LEVEL SECURITY`. Downgrade of
a new table refuses to drop it when it contains rows unless the migration's
documented archival precondition is met. Each revision is tested from revision
017 up and back to its direct predecessor, plus fresh install to head.

## 6. API contract

### 6.1 Organization context

Add `establish_api_context()` to `api/dependencies.py`. It creates the existing
domain `Principal`, calls `DORRuntime.establish_context(organization_id,
actor_id)`, and maps missing organization/membership to HTTP 403. Endpoints may
accept an organization ID as requested context, but must never pass it directly
to a store before this check.

Request bodies exclude ownership and server fields:

- no `organization_id`;
- no fingerprint, version, approver, timestamps, status, resolved connection,
  model, assignment, authority, or performance fields supplied by the client.

### 6.2 New routers

| Router | Prefix | Commands/queries |
| --- | --- | --- |
| `api/endpoints/bot_governance.py` | `/api/v1/bot-governance` | create/list/disable connection; create/list/disable deployment/profile |
| `api/endpoints/council_configuration.py` | `/api/v1/council-configuration` | create/version/list roles, templates, allocations; validate template |
| `api/endpoints/bot_selection.py` | `/api/v1/bot-selections` | request selection, read decision, freeze assignment, explicit substitution |
| `api/endpoints/evaluations.py` | `/api/v1/evaluations` | create/version rubric, request evaluation, read records/snapshots |
| `api/endpoints/factory_work.py` | `/api/v1/factory-work` | compile/read/publish packages, read candidates and integration status |

Mutation endpoints call the central authority capability before persistence:

| Action | Capability/action ID |
| --- | --- |
| Manage connection/profile | `bot_catalog.manage` |
| Manage role/template/allocation | `council_configuration.manage` |
| Override or substitute selection | `bot_selection.override` |
| Create/version rubric | `evaluation_rubric.manage` |
| Publish work package | `factory_work.publish` |
| Select competing winner | `factory_candidate.select` |
| Execute integration | `factory.integrate` |
| Publish final PR | existing `release.publish` |

All routers are added to both `api/api_surface.py` and the identical ordered
router list in `api/main.py`. API inventory tests fail on any mismatch.

### 6.3 Error mapping

| Domain error | HTTP |
| --- | ---: |
| Not found or cross-tenant invisible | 404 after valid organization context |
| Organization membership/capability denied | 403 |
| Invalid schema or lifecycle transition | 422 |
| OCC, idempotency, stale base, frozen assignment conflict | 409 |
| No eligible allocated bot | 409 with `NO_ELIGIBLE_BOT` |
| Provider/evaluator temporarily unavailable | 503 |
| Governed provider failed after dispatch | 502 |

Responses never reveal whether an ID exists in another organization.

## 7. Selection algorithm contract

### 7.1 Request fingerprint

Canonical JSON contains:

- organization, scope/session/task, role and requested allocation version;
- repository and exact base SHA;
- requirements, architecture, contract, input and template fingerprints;
- required capabilities/tools;
- risk and data classification;
- locality, budget, latency and availability requirements;
- producer assignments relevant to independence;
- selection policy version and performance snapshot IDs.

### 7.2 Hard filters

Evaluate in stable order and retain every applicable exclusion reason:

1. allocated membership;
2. same organization;
3. active profile, deployment, and connection;
4. AgentRecord exists, is active, and declares required capabilities;
5. profile capabilities remain a subset of AgentRecord capabilities;
6. tool permission;
7. data boundary and locality;
8. budget ceiling;
9. profile/connection concurrency;
10. independence policy;
11. provider health only when the policy permits availability as a hard filter.

Failure produces a durable blocked decision. It does not select a fallback.

### 7.3 Ranking

The policy declares named score components, weights, missing-data defaults,
minimum sample count, confidence floor, decay version, and exploration rate.
Hard constraints are never score components. Final order is:

1. descending normalized score;
2. descending evidence confidence;
3. ascending expected cost;
4. ascending bot profile ID as deterministic final tie-break.

Critical risk sets exploration to zero. Exploration can select only an eligible
allocated profile and is itself a deterministic function of request fingerprint
and policy seed. Identical complete snapshots reproduce the same selection.

### 7.4 Decision and assignment identity

`decision_id` is the SHA-256 content fingerprint of request, allocation,
candidates, exclusions, scores, selected snapshot, and policy evidence. It has
no UUID or timestamp input. A blocked decision receives the same treatment.

`assignment_id` is derived from decision ID, scope, role, selected profile,
complete connection/deployment/model/prompt snapshot, input/base SHA, and expiry.
Substitution creates a new selection request and assignment, references the old
assignment, and emits an outbox/audit event.

## 8. Council integration contract

### 8.1 Backward-compatible transition

`CouncilOrchestrator.run()` gains a required `CouncilAssignmentPlan` only after
all production callers are migrated. During one compatibility release:

- tests may use an explicit legacy-template factory;
- production configuration cannot use implicit `candidates[0]`;
- missing plan is a start failure outside the named compatibility factory.

Then remove `_select_assignments()` from the production path.

### 8.2 Provider routing

Replace the single orchestrator-wide provider assumption with a
`CouncilProviderRouter` protocol. It receives a frozen assignment and returns a
configured `CouncilProvider` adapter. `CouncilTurnRequest` binds:

- assignment ID/fingerprint;
- provider connection and model deployment snapshots;
- prompt version;
- role ID and protocol function;
- all existing agenda/session/hypothesis/revision content.

The turn ID includes those values. A restarted turn resolves the same adapter
snapshot or fails closed; it never chooses a replacement implicitly.

### 8.3 Template execution

The template supplies ordered stages. `proposer` produces or revises the
hypothesis, `reviewer` stages may run in parallel but commit one atomic Council
round, and `verifier` executes only after all blocking disputes are resolved.
The existing dispute, vote, evidence, OCC, outbox, Anti-Tube, readiness, and
Authority boundaries remain authoritative.

## 9. Evaluation and local learning contract

### 9.1 Evaluation order

1. Validate subject schema, fingerprints, assignment and base SHA.
2. Execute every required deterministic check through existing sandbox/test
   boundaries and persist attestations.
3. If a hard check fails, record `fail` or `rework` and skip semantic approval.
4. Select/freeze an independent evaluator from its human-approved role pool.
5. Invoke the evaluator through `GovernedLLMRuntime` with a versioned schema.
6. Verify all rubric criteria and evidence requirements are present.
7. Persist one immutable evaluation record.
8. Append one or more event-based performance observations.

### 9.2 Independence evaluator

One canonical evaluator compares producer and evaluator snapshots at the
configured level: profile, connection, deployment, model family, provider
adapter, or brand. `any` is not a valid independence level. A stricter level
implies different identity at the preceding levels where applicable.

### 9.3 Local evaluator

A LibreChat-hosted local model is configured as an ordinary provider connection
and bot profile allocated to evaluator roles. Its output is semantic evidence.
It cannot:

- change pools or scoring policy without the configured autonomy grant;
- override a hard failure;
- edit past observations;
- execute, integrate, deploy, or publish;
- become independent merely because it is local.

### 9.4 Observation events

Use one fact per observation, for example:

- `proposal.accepted`
- `candidate.delivered`
- `deterministic_checks.passed`
- `independent_review.passed`
- `integration.passed`
- `release.succeeded`
- `rework.requested`
- `regression.detected`
- `rollback.performed`
- `incident.confirmed`
- `human.assessment`
- `usage.cost`, `usage.tokens`, `usage.latency`

This avoids treating non-applicable pipeline stages as failures. Snapshots are
role/task-context aggregates, never mutable properties on `BotProfile`.

## 10. Factory execution contract

### 10.1 Compilation

`FactoryTaskSynthesizer` consumes only approved requirement, architecture, and
contract fingerprints. It emits a deterministic DAG. Every WorkPackage contains
criterion IDs, dependency IDs, exact base SHA, write scopes, execution mode,
candidate count, role allocation, policy, limits, and idempotency key.

Overlapping write scopes cause either a dependency edge or an explicit
`WRITE_SCOPE_CONFLICT`; they are never silently scheduled concurrently.

### 10.2 Queue and claim ownership

Scheduler publishes only `{organization_id, work_package_id, fingerprint}` to
the existing `DatabaseQueue`. Worker flow is:

1. `DatabaseQueue.claim(topic="factory.work", worker_id=...)`;
2. load package by tenant and verify payload fingerprint;
3. acquire the existing AI-4 replay-ledger claim for governed execution;
4. select/freeze the implementation assignment if not already frozen;
5. create an isolated workspace from exact base SHA;
6. execute, attest, and deliver candidate;
7. complete replay ledger with its fencing token;
8. acknowledge queue with the exact lease ID.

Queue `lease_id` fences queue ack/fail. AI-4 replay `fencing_token` fences
execution completion. Terminal branch/integration effects use the side-effect
store's own fencing token. These tokens are not interchangeable.

### 10.3 Workspace and branch

Refactor reusable worktree primitives from `services/git_pr_publisher.py` only
after characterization tests preserve PR behavior. `FactoryWorkspaceManager`
must:

- resolve exact 40-character base SHA before worktree creation;
- validate generated branch names from IDs, never accept raw arbitrary names;
- use one new worktree and branch per execution/candidate;
- enforce allowed/denied paths before commit;
- record ordered commits, head SHA, patch fingerprint, and affected paths;
- remove worktree safely without deleting the delivered branch;
- never force-push or write a protected branch.

Candidate branch push uses action `factory.candidate.push` through
`SideEffectCoordinator`. Reconciliation checks the remote branch head and
request fingerprint before deciding whether to replay or halt.

### 10.4 Competing candidates

For `candidate_count = N`, synthesize N execution assignments with one logical
task/package fingerprint and distinct candidate IDs. Candidate evaluators must
meet independence policy against every producer they evaluate. Selection is an
atomic store transaction that yields one winner or `no_winner`. Losers remain
immutable evidence and are never deleted to improve performance history.

## 11. Integration and release contract

Integration Controller:

1. requires capability/action `factory.integrate`;
2. validates all candidates are accepted and heads unchanged;
3. validates base SHA, dependency order, write scopes, and attestations;
4. claims terminal effect `factory.integrate` using plan fingerprint;
5. creates one deterministic integration branch in an isolated worktree;
6. merges/cherry-picks exact candidate commits in plan order;
7. halts visibly on conflict;
8. runs the complete required suite in the existing sandbox boundary;
9. persists receipt using the active side-effect fencing token;
10. returns the attested patch/integration metadata to ReleaseExecutor.

`GitPRPublisher.publish_patch_as_pr()` remains the only PR publisher. It still
requires its existing `release.publish` grant and attested passing tests. The
integration grant cannot be reused as the release grant.

## 12. PR and delivery sequence

Each PR is independently reviewable and keeps one Alembic head.

| PR | Branch | Deliverable | Migration |
| ---: | --- | --- | --- |
| 1 | `feature/bot-catalog` | Bot domain, store, provider resolution metadata, API | 018 |
| 2 | `feature/council-role-allocation` | User roles, templates, pools, GUI-facing API | 019 |
| 3 | `feature/bot-selection-assignments` | Hard filters, ranking, frozen assignments | 020 |
| 4 | `feature/council-assignment-routing` | Template-driven Council and provider router | none |
| 5 | `feature/bot-evaluation-ledger` | Rubrics, local evaluator, observations/snapshots | 021 |
| 6 | `feature/factory-work-candidates` | DAG, queue dispatch, workspace, candidates | 022 |
| 7 | `feature/factory-integration-controller` | Candidate winner, integration receipt, release handoff | 023 |
| 8 | `test/multi-bot-factory-e2e` | 20-worker, crash, race, competing-candidate E2E | none |
| 9 | `feature/multi-bot-control-plane-ui` | GUI for connections, profiles, roles, pools, selections, evidence | only if UI persistence needs it |

If PRs are stacked, every PR description states its base. A migration revision
is not split across independently mergeable branches.

## 13. Test matrix

### 13.1 Unit/domain

- canonical fingerprints ignore timestamps/random IDs and change for every
  behavior-affecting field;
- configuration dataclasses/Pydantic models are frozen and reject whitespace,
  duplicate IDs, invalid state, and unsupported protocol functions;
- capability subset and independence levels;
- ranking tie-break and deterministic exploration;
- hard failures dominate semantic scores;
- WorkPackage transition and write-scope rules.

### 13.2 Persistence/migrations

- fresh upgrade 017 to each new head and complete fresh install;
- downgrade to every predecessor under documented preconditions;
- composite keys/FKs and unique winner/integration constraints;
- RLS enabled and forced on every new PostgreSQL table;
- SQLite explicit cross-tenant not-found behavior;
- OCC conflicts, immutable rows, append-only correction chain;
- selection and side-effect replay after process restart.

### 13.3 API/adversarial

- request-supplied organization ownership cannot be persisted without verified
  runtime membership;
- cross-tenant IDs are not distinguishable from missing IDs;
- extra fields and secret values are rejected;
- authorization denied for every mutation capability;
- API router inventory fails if new router is missing or a legacy router mounts;
- selection API cannot inject an unallocated profile or performance snapshot;
- assignment mutation and silent substitution are rejected.

### 13.4 Required contract acceptance tests

| ID | Test | Required proof |
| --- | --- | --- |
| MBF-01 | Six same-brand connections | distinct connections/profiles/quotas and audit identities |
| MBF-02 | Allocation escape | HTTP and direct-store tampering cannot select outside pool |
| MBF-03 | Hard exclusion | disabled, cross-tenant, budget, locality and capability reasons |
| MBF-04 | Deterministic replay | identical full snapshots yield same decision ID/fingerprint |
| MBF-05 | No silent fallback | provider failure creates visible failure/substitution state |
| MBF-06 | Independent evaluation | producer cannot be sole evaluator at every policy level |
| MBF-07 | Hard gate dominance | perfect semantic score cannot override failed required test |
| MBF-08 | Append-only learning | correction preserves old observation and snapshot boundary |
| MBF-09 | Twenty workers | isolated worktrees/branches and no overlapping write ownership |
| MBF-10 | Stale delivery | reclaimed queue/execution claims reject old lease/token |
| MBF-11 | Competing branches | three delivered candidates, zero or one accepted winner |
| MBF-12 | Push crash recovery | remote branch reconciled; no duplicate branch or PR |
| MBF-13 | Base SHA invalidation | assignment/evaluation/attestation becomes unusable |
| MBF-14 | Unique integration | concurrent integrators create one effect/receipt and one PR |

MBF-09 through MBF-14 use real SQLAlchemy persistence and real temporary Git
repositories. Fake providers are permitted; fake leases, worktrees, receipts,
or manually synthesized task results are not.

## 14. Definition of Done by phase

### Phase 1 — Catalog and allocation

- migrations 018/019 upgrade, downgrade, RLS and constraints pass;
- six same-brand identities are proven;
- API is tenant- and authority-scoped;
- credentials cannot appear in DB, response, logs, prompts, or fingerprints;
- roles/templates/allocations round-trip exactly and are provider-neutral.

### Phase 2 — Selection and Council

- deterministic blocked/selected decisions persist and replay;
- frozen assignments survive restart;
- Council uses template assignments and no production `candidates[0]` path;
- provider failure cannot silently change assignment;
- current Council evidence/readiness/Authority tests remain green.

### Phase 3 — Evaluation and learning

- deterministic and semantic evidence remain separate;
- local evaluator operates through governed LLM replay;
- independence is enforced at all configured levels;
- observations are event-based and append-only;
- selection can consume only versioned snapshots meeting confidence policy.

### Phase 4 — Parallel factory

- contract-to-DAG synthesis is deterministic;
- queue, replay and side-effect tokens are correctly separated;
- 20 concurrent executions create isolated candidate branches;
- stale workers cannot deliver and failed workers recover safely;
- competing candidates yield at most one winner.

### Phase 5 — Integration and release

- exact candidate heads integrate in deterministic order;
- conflicts halt without partial success;
- crash recovery produces one receipt;
- complete-suite attestation binds the integration head;
- existing release publisher produces at most one PR under its own grant.

### Complete product proof

Through authenticated HTTP, configure multiple connections and profiles,
define roles/template/pools, start Council, approve contracts, compile work,
run 20 workers, produce competing and collaborative branches, evaluate and
select candidates, integrate them, run complete E2E verification, approve the
release gate, and publish exactly one PR. Restart Council, workers, evaluator,
and integrator at injected checkpoints without losing authority, state,
evidence, or idempotency.

## 15. Explicit non-goals for this program

- automatic fine-tuning of the local evaluator;
- unrestricted allocator modification of human pools;
- provider-specific roles or hardcoded brand preference;
- direct model access to credentials;
- direct bot writes to protected branches;
- automatic semantic merge-conflict resolution;
- replacing DOR Authority, Council evidence, queue, replay ledger, sandbox, or
  GitPRPublisher;
- microservice extraction before the modular-monolith reference flow is proven.

## 16. Approval checklist

Before Phase 1 coding begins, the human owner approves:

- architecture and contract version 1.0;
- protocol-function vocabulary;
- table and migration ownership;
- mutation authority action IDs;
- progressive autonomy defaults (`0` or `1` initially);
- independence defaults for Council and implementation review;
- whether role/template configuration belongs in the first GUI release;
- whether provider credentials are resolved through the existing secret manager
  or a separately approved credential boundary.

After approval, changes to these decisions require a versioned architecture
amendment rather than silent implementation drift.
