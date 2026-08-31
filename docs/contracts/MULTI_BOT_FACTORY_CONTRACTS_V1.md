# Governed Multi-Bot Factory Contracts v1

```yaml
status: proposed
version: 1.0.0
architecture: docs/architecture/GOVERNED_MULTI_BOT_FACTORY_V1.md
approval_required: true
```

## 1. Contract principles

All identifiers are canonical non-empty strings. Every aggregate is scoped by
`organization_id`. Mutable configuration uses optimistic versioning; runtime
assignments and evidence records are immutable. Content fingerprints are
SHA-256 over canonical JSON excluding explicitly documented operational fields.

The machine-readable schemas are:

- `docs/schemas/bot-governance-v1.schema.json`
- `docs/schemas/factory-work-package-v1.schema.json`

## 2. Bot governance contract

### 2.1 ProviderConnection

Represents one tenant-owned provider account or local deployment endpoint.

Required fields:

- `connection_id`, `organization_id`, `brand`, `provider_type`;
- `endpoint`, `secret_reference`, `region`, `data_boundary`;
- `concurrency_limit`, `enabled`, `version`.

`secret_reference` is opaque. The referenced credential never crosses this
contract. Multiple connections may share `brand` and `provider_type`.

### 2.2 ModelDeployment

Identifies the concrete model available through one connection:

- `deployment_id`, `connection_id`, `model_id`, `model_family`;
- the exact `connection_version` used by the deployment;
- context and output limits;
- structured-output and tool capabilities;
- lifecycle status and immutable deployment revision.

### 2.3 BotProfile

Represents one selectable bot identity:

- `bot_profile_id`, `organization_id`, `agent_identity`;
- `display_name`, `deployment_id`, `prompt_version`;
- the exact `deployment_revision` used by the profile;
- declared capabilities and permitted tools;
- data policy, budget policy, concurrency limit, lifecycle state.

Credentials, live lease state, performance aggregates, and authority grants are
forbidden in the profile.

### 2.4 RoleDefinition

A human-defined seat in Council or production:

- `role_id`, `organization_id`, `name`, `purpose`;
- one `protocol_function` from the provider-neutral runtime vocabulary;
- required capabilities;
- input and output schema references;
- evaluation rubric reference;
- whether independent verification is required;
- lifecycle and version.

Provider and brand names are forbidden role semantics.

The protocol functions are `conversation_owner`, `proposer`, `reviewer`,
`verifier`, `implementer`, `candidate_evaluator`, and `integrator`. They define
runtime behavior, not the role's display name, bot, provider, or model.

### 2.5 CouncilTemplate

A template is immutable by version and defines the choreography selected in the
GUI. It contains ordered stages. Every stage declares a protocol function, one
or more role IDs, minimum and maximum assignments, whether turns may run in
parallel, and whether failure blocks the next stage. Referenced roles and their
allocation versions are frozen when a session starts.

### 2.6 RoleAllocationPool

The human-approved many-to-many relation between a role and eligible profiles:

- `allocation_id`, `role_id`, `allowed_bot_profile_ids`;
- preferred profiles and explicitly ordered fallbacks, if any;
- hard selection constraints and independence policy;
- autonomy level, approval provenance, version and fingerprint.

The Selection Engine may narrow this set but cannot expand it.

### 2.7 SelectionRequest and SelectionDecision

The request binds:

- organization, role and allocation versions;
- task/session identity and repository base SHA;
- required capabilities, risk and data classification;
- budget, latency, locality, independence and availability constraints.

The immutable decision records:

- all candidate bot profile IDs;
- excluded candidates with structured reason codes;
- scored eligible candidates with metric snapshots;
- selected bot, deployment, connection and prompt version;
- selection policy and performance-snapshot versions;
- rationale and decision fingerprint.

No selection is executable until backend validation proves that the selected
profile belonged to the bound allocation version.

### 2.8 SessionAssignment

Freezes a selection for one Council session or work execution:

- assignment, session/task, role and bot identities;
- agent, connection, deployment, model and prompt snapshot;
- selection-decision fingerprint;
- input and repository fingerprints;
- creation time and optional expiry.

It is append-only. Substitution creates a new explicit assignment linked by
`supersedes_assignment_id`; it does not mutate the original.

## 3. Evaluation contract

### 3.1 EvaluationRubric

A rubric is versioned before the subject is produced. It declares:

- subject type and applicable role/task classes;
- weighted semantic criteria;
- deterministic check requirements;
- hard failures;
- minimum passing score;
- independence policy;
- evidence requirements.

The producer cannot create or modify the effective rubric for its own output.

### 3.2 EvaluationRecord

An immutable evaluation binds:

- evaluator assignment and subject fingerprint;
- rubric and repository revision;
- deterministic check results and attestations;
- semantic criterion results with evidence references;
- hard-failure codes;
- outcome: `pass`, `fail`, `rework`, or `inconclusive`;
- confidence, score, provenance, and fingerprint.

An LLM-generated semantic score is advisory evidence. A deterministic hard
failure forces `fail` or `rework` regardless of the aggregate score.

### 3.3 PerformanceObservation

One immutable outcome signal derived from a real event:

- accepted/rejected candidate;
- deterministic test result;
- reviewer precision confirmed later;
- rework count;
- integration result;
- regression, rollback, or incident;
- human assessment;
- cost, tokens, and latency.

It binds bot profile, role, task class, model/prompt version, rubric version,
event source, evidence reference, and observation time. Corrections append a
new observation referencing the superseded observation.

### 3.4 PerformanceSnapshot

An allocator consumes a signed/versioned aggregate, not arbitrary chat memory.
The snapshot states sample counts, time window, metric definitions, confidence,
decay policy, excluded observations, and source ledger position.

## 4. Factory work contract

### 4.1 WorkPackage

A work package is the only input a production bot may implement. It binds:

- organization, workflow and logical task;
- approved requirements, architecture, and contract fingerprints;
- exact repository and base commit SHA;
- dependency task IDs;
- acceptance criteria and required checks;
- allowed and denied repository paths;
- execution mode and candidate count;
- role allocation and selection policy;
- resource, budget, timeout, retry, and risk policy;
- idempotency key.

Changing any binding creates a new package fingerprint and invalidates stale
assignments and attestations.

### 4.2 ExecutionAssignment

Combines a work package with a frozen bot selection and queue claim:

- execution ID and attempt;
- work-package fingerprint;
- session assignment;
- worker ID, lease ID, fencing token and lease expiry;
- workspace and branch identifiers;
- status and timestamps.

Only the current fencing token can deliver a candidate.

### 4.3 CandidateDelivery

An immutable candidate contains:

- candidate, task, execution, assignment and organization IDs;
- repository, base SHA, branch, head SHA and ordered commit SHAs;
- patch fingerprint and affected paths;
- producer attestation;
- deterministic and independent evaluation references;
- terminal delivery status.

A candidate is not an accepted result and cannot itself authorize integration.

### 4.4 CandidateSelection

For `competing_candidates`, an independent selection records all candidates,
the comparison rubric, evidence, exclusions, winner or `no_winner`, and its
authority provenance. A producer of any candidate cannot be the sole selector.

At most one winner exists for one logical task and contract fingerprint.

### 4.5 IntegrationPlan

The plan binds:

- one workflow and repository base SHA;
- an ordered list of accepted candidate IDs and exact head SHAs;
- dependency and compatibility checks;
- integration branch;
- idempotency key and required authority action.

The Integration Controller must reject changed candidate heads, stale base SHA,
missing attestations, overlapping write scopes without an explicit resolution,
or an expired authority grant.

### 4.6 IntegrationReceipt

Records the unique authoritative integration result:

- plan fingerprint and fencing token;
- integration branch and head SHA;
- merge/conflict outcomes;
- complete-suite attestation;
- status and immutable side-effect receipt.

Release publication consumes this receipt and still requires its own grant.

## 5. State machines

### 5.1 Selection

```text
REQUESTED -> ELIGIBILITY_CHECKED -> SELECTED -> FROZEN
                       |                |
                       v                v
                    BLOCKED        SUPERSEDED
```

`BLOCKED` is required when no allocated candidate satisfies hard constraints.

### 5.2 Work package

```text
DRAFT -> READY -> CLAIMED -> EXECUTING -> DELIVERED -> VERIFYING
                    |          |                         |
                    v          v                         v
                 EXPIRED    FAILED             ACCEPTED/REWORK/REJECTED
```

A reclaimed attempt receives a new lease and fencing token. The stale attempt
cannot transition the current package or register a candidate.

### 5.3 Candidate and integration

```text
CANDIDATE -> VERIFIED -> ACCEPTED -> INTEGRATION_PLANNED -> INTEGRATED
     |           |          |                  |
     v           v          v                  v
  INVALID     REWORK     REJECTED           CONFLICT
```

## 6. API boundary

The future authenticated, tenant-derived API surface should expose resources,
not provider-specific operations:

```text
/bot-connections
/bot-profiles
/role-definitions
/role-allocations
/selection-decisions
/evaluation-rubrics
/evaluation-records
/performance-snapshots
/work-packages
/candidate-deliveries
/integration-plans
```

Organization identity is derived from the verified principal and never trusted
from an unverified request parameter. Secret material is accepted only through
a secret-manager integration and is never returned.

## 7. Required error codes

| Code | Meaning |
| --- | --- |
| `ALLOCATION_NOT_FOUND` | No visible role pool for the organization |
| `NO_ELIGIBLE_BOT` | All allocated candidates failed hard constraints |
| `INDEPENDENCE_VIOLATION` | Producer/verifier relationship violates policy |
| `SELECTION_STALE` | Allocation, repository, or metric snapshot changed |
| `ASSIGNMENT_FROZEN` | Mutation attempted after execution began |
| `SUBSTITUTION_REQUIRES_APPROVAL` | Visible fallback needs a gate |
| `RUBRIC_MISMATCH` | Evaluation used another subject/rubric revision |
| `DETERMINISTIC_GATE_FAILED` | Hard validation failed |
| `STALE_FENCING_TOKEN` | Old worker attempted a state transition |
| `CANDIDATE_HEAD_CHANGED` | Branch no longer matches attested head |
| `WRITE_SCOPE_CONFLICT` | Candidate paths overlap without resolution |
| `INTEGRATION_ALREADY_EXISTS` | Idempotent replay or conflicting plan |

## 8. Acceptance tests required before implementation is complete

1. Register six provider connections under one brand and preserve distinct bot
   profile identities and quotas.
2. Prove selection cannot escape an allocation pool through API tampering.
3. Prove disabled, cross-tenant, over-budget, or data-incompatible profiles are
   excluded with stable reason codes.
4. Prove identical request and policy snapshots reproduce the same selection.
5. Prove no silent fallback occurs when the selected provider fails.
6. Prove the producer cannot be sole evaluator under independent policy.
7. Prove a hard test failure cannot be overridden by semantic scoring.
8. Prove performance history is append-only and corrections are traceable.
9. Run twenty concurrent workers and prove worktree and branch isolation.
10. Reclaim an expired task and prove the stale worker cannot deliver.
11. Produce three competing branches and prove at most one is accepted.
12. Crash after branch push and reconcile without duplicate branch or PR.
13. Change base SHA and prove assignments and test attestations become stale.
14. Integrate multiple accepted candidates and prove exactly one integration
    receipt and one release PR are produced.
