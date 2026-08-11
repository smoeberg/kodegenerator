# P5-08 — Release Resolution Contract

## Purpose

P5-08 is the policy-resolution boundary after P5-07 reconciliation. It consumes the immutable reconciliation observation and, when required, the immutable observed release outcome. It produces an immutable resolution record describing the next permitted disposition.

Flow:

`P5-04 → P5-05 → P5-06 → P5-07 → P5-08`

P5-08 does not execute a release, retry a release, repair records, or perform external side effects.

## Inputs

P5-08 MUST require:

- a `ReleaseReconciliationRecord`;
- the corresponding immutable `ReleaseDispatchRecord`;
- the corresponding `ReleaseOutcomeRecord` when reconciliation status is not `OUTCOME_MISSING`;
- preserved upstream identity and provenance.

The resolution boundary MUST validate that the supplied records refer to the same dispatch/finalization identity chain. Conflicting identity or provenance MUST fail closed.

## Resolution dispositions

A resolution MUST contain exactly one disposition:

- `NO_ACTION` — no downstream intervention is required by the supplied policy and observations;
- `RETRY_REQUESTED` — a retry may be requested by a later execution boundary;
- `ESCALATION_REQUIRED` — the case requires controlled human or supervisory handling;
- `RELEASE_BLOCKED` — further release activity is prohibited until the blocking condition is resolved by an authorized boundary.

These dispositions are instructions to downstream policy/execution infrastructure, not execution commands. P5-08 MUST NOT itself retry, dispatch, block an external system, or escalate through an external side effect.

## Normative behavior

- `RECONCILED` MUST resolve to `NO_ACTION` when the observed outcome is accepted and no explicit policy requires another disposition.
- `OUTCOME_MISSING` MUST NOT silently become an automatic retry. The resolution MUST be policy-driven and fail closed when no explicit retry policy is supplied.
- `MISMATCH` MUST NOT be normalized or repaired. Without an explicit trusted policy, it MUST resolve to `ESCALATION_REQUIRED` or `RELEASE_BLOCKED`, never to an automatic retry.
- An unknown reconciliation status, missing required provenance, or conflicting identity MUST fail closed.
- A resolution MUST preserve the reconciliation fingerprint and the upstream identity chain.

## Policy boundary

P5-08 MAY consume an explicit, deterministic resolution policy. The policy MUST be supplied as an input/configuration of the resolution boundary rather than inferred from artifact contents or mutable external state.

A policy MUST NOT grant authority that is absent upstream. P5-08 cannot create, modify, or elevate verification or release eligibility authority.

## Authority boundary

P5-08 MUST NOT:

- create or modify a `VerificationDecision`;
- change P3-20 authority or verifier identity;
- create release eligibility;
- mutate P5-04, P5-05, P5-06, or P5-07 records;
- repair mismatched records;
- infer success from artifacts;
- bypass a blocked or failed authoritative outcome;
- execute retry, dispatch, publication, deployment, escalation, or other external side effects.

P5-08 is a **consumer of authoritative observations and explicit policy**, not a source of authority or an execution engine.

## Immutability and determinism

The resolution record MUST be immutable after construction. Its canonical representation and fingerprint MUST be deterministic for identical inputs and policy.

The same reconciliation identity plus the same policy MUST produce the same logical resolution. A conflicting resolution MUST NOT silently replace an existing one.

## Failure semantics

P5-08 MUST fail closed on:

- missing required inputs;
- invalid or conflicting provenance;
- unknown reconciliation status;
- policy ambiguity where a safe disposition cannot be established.

Failures MUST NOT mutate upstream records or create an external side effect.

## Non-responsibilities

P5-08 does not perform release execution, retry scheduling, transport, deployment, publication, verification, authorization, or automatic remediation. Those responsibilities belong to later, explicitly authorized boundaries.
