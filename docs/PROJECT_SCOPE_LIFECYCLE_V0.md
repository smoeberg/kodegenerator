# Project Scope & Lifecycle v0

Status: IMPLEMENTED THROUGH GUI-101

## Purpose

Define one canonical project identity and lifecycle boundary for scope changes,
execution authority, completion, cancellation, archive, and continuation without
rewriting provenance or introducing a persistent decision graph.

## Original problem

Before SC-101, DOR had two partially separate project identities:

- the first-party Control Plane `Project` aggregate (`project_id`); and
- the Phase-4 delivery chain beginning at immutable `OnboardingIntent` and
  continuing through Project Audit, planning, Implementation Agent, governed
  patch apply, delivery certification, and traceability.

Before SC-101B, the planning layer produced a content-addressed
`plan_request_fingerprint`, but that fingerprint was not yet an authoritative
server-side execution boundary all the way through proposal, authority, apply,
and certification. A proposal made under one plan could therefore survive a
later scope change unless downstream boundaries explicitly rejected it.

Before PC-101, the `Project` aggregate also had no terminal project lifecycle
beyond `created` and `launch_requested`; there was no governed definition of
active, completion-pending, completed, cancelled, archived, or continuation
semantics.

## Canonical identity hierarchy

```text
organization_id
    -> project_id
        -> onboarding_intent_id
            -> audit provenance
                -> plan_request_fingerprint
                    -> work/proposal/authority/apply
                        -> delivery/certificate
                            -> project completion
```

`project_id` is the operational container. `OnboardingIntent` is immutable
charter provenance. `plan_request_fingerprint` is the exact active scope
identity for executable work.

## Active scope invariants

1. Exactly one active `plan_request_fingerprint` exists per active project.
2. Scope activation is atomic and revision-checked; concurrent activations
   cannot both win.
3. `project_id` and `plan_request_fingerprint` are hard-bound into executable
   Implementation Agent requests and their content identity.
4. Scope-sensitive authority grants bind the same project + plan identity.
5. After scope P1 is superseded by P2:
   - no new P1 work may be claimed;
   - cooperative cancellation of in-flight P1 work is attempted;
   - cancellation success is never required for correctness;
   - P1 outputs remain historical but cannot become executable under P2;
   - stale apply is fail-closed;
   - stale certification is fail-closed.
6. Scope changes never automatically roll back already committed external side
   effects; compensation is a separate governed action when required.

## Persistence decision

v0 extends the existing durable `Project` current-state aggregate rather than
creating a separate scope decision graph. The project row remains the
materialized current-state authority and optimistic `revision` remains the
concurrency boundary. Append-only domain events retain activation/supersession
history.

If implementation proves that the existing aggregate cannot provide atomic
current-scope semantics without violating existing invariants, coding must stop
and return to the semantic gate before introducing a separate table.

## Project lifecycle

```text
CREATED
  -> LAUNCH_REQUESTED
  -> ACTIVE
      -> COMPLETION_PENDING -> COMPLETED -> ARCHIVED
      -> CANCELLED
```

### ACTIVE

The project may hold an active scope and accept governed work.

### COMPLETION_PENDING

A closure request freezes new ordinary work and new scope amendments while DOR
verifies exact closure evidence. It is not itself completion.

### COMPLETED

The approved project scope has been delivered and verified under an immutable
`ProjectCompletionRecord`. Completed projects are read-only for ordinary work
and are never reopened in place.

### CANCELLED

The project was intentionally stopped without satisfying completion. Cancelled
must never be represented as completed.

### ARCHIVED

Catalog/storage state only. Archive does not delete provenance, events,
certificates, evidence, completion records, or artifact identities.

### Continuation

New work after completion creates a new project with
`continued_from_project_id=<completed project>` and a new active-scope lineage.
The completed project remains historically true and immutable.

## Completion contract

A project may move from `COMPLETION_PENDING` to `COMPLETED` only when the
backend verifies at minimum:

- expected exact project revision;
- expected exact active plan fingerprint;
- no pending scope amendment;
- no claimed/running ordinary work;
- no unresolved governance gate;
- no stale executable output;
- final assembled-system integration verification PASS;
- final delivery certificate provenance exists;
- final requirement traceability for the final scope is COMPLETE.

Completion produces one immutable content-addressed record binding at least:

- `project_id` and organization;
- final project revision;
- final onboarding intent identity;
- final `plan_request_fingerprint`;
- final repository commit identity;
- final delivery certificate IDs;
- final traceability manifest IDs;
- final integration evidence IDs;
- completing principal and timestamp.

## Delivery plan

SC-101A, SC-101B, SC-101C, PC-101, and GUI-101 are implemented on `main`.
SC-102 and SC-103 remain explicitly deferred and are not part of the completed
PLSC-100 delivery scope.

### SC-101A — Project identity bridge

Implemented. Carry exact `project_id` through onboarding/audit/planning into
Implementation Agent provenance and fail closed on cross-project/cross-tenant
drift.

### SC-101B — Active scope authority boundary

Implemented. Add exact active-plan current state to `Project`; hard-bind project
+ plan into Implementation Agent request identity, authority, apply and delivery
certification; stale scope must block.

### SC-101C — In-flight supersession

Implemented. Prevent new stale claims and attempt cooperative cancellation at
natural checkpoints. Cancellation remains an optimization only.

### PC-101 — Project completion boundary

Implemented via PR #253. Define and implement
completion-pending/completed/cancelled/archive and immutable completion evidence.

### GUI-101

Implemented via PR #255. Adds a dedicated lifecycle command surface over
canonical backend project state, binds mutations to the displayed server-owned
snapshot, surfaces fail-closed authorization/conflict responses, and preserves
the rule that the GUI never becomes an authority boundary.

### SC-102 / SC-103

Deferred. No dependency graph, percentage-based scope classification,
automated reuse planner, or `ReuseEvidence` optimization is part of SC-101.

## Critical SC-101 acceptance scenario

```text
P1 active
-> worker starts work bound to project + P1
-> P2 activates while P1 work is in flight
-> P1 cancellation is attempted
-> P1 output cannot be applied or certified under P2 even if cancellation fails
-> a new proposal under project + P2 can apply and certify successfully
```

## Non-goals

- no persistent decision graph;
- no automatic artifact reuse;
- no correctness threshold based on affected percentage;
- no automatic rollback of external side effects;
- no reopening a completed project in place;
- no GUI-only enforcement.
