# P5-07 Release Reconciliation Contract

## Purpose

P5-07 reconciles an immutable P5-05 `ReleaseDispatchRecord` with an immutable P5-06 `ReleaseOutcomeRecord`. It records whether the observed outcome is consistent with the dispatch.

## Input

- `ReleaseDispatchRecord`
- `ReleaseOutcomeRecord`, when available

## Output

P5-07 produces an immutable `ReleaseReconciliationRecord`.

Allowed reconciliation statuses:

- `RECONCILED` — dispatch and observed outcome are consistent.
- `OUTCOME_MISSING` — a dispatch exists but no outcome has been observed.
- `MISMATCH` — an outcome exists but its identity/provenance does not match the dispatch.

## Authority boundary

P5-07 MUST NOT:

- create or evaluate release eligibility;
- perform verification;
- create or modify verification authority;
- dispatch or retry a release;
- mutate a `ReleaseDispatchRecord`;
- mutate a `ReleaseOutcomeRecord`;
- alter organization identity;
- repair or rewrite mismatched records.

P5-07 is an observational reconciliation boundary only.

## Identity and provenance

A reconciliation MUST preserve the upstream identity chain. Matching requires the dispatch and outcome to agree on the dispatch identity, finalization fingerprint, verifier identity, and release identity/reference where applicable.

A mismatch MUST be recorded as `MISMATCH`; P5-07 MUST NOT silently normalize conflicting values.

## Immutability

`ReleaseReconciliationRecord` MUST be immutable after construction. Both upstream records MUST remain unchanged.

## Idempotency

The same dispatch/outcome identity pair MUST produce the same logical reconciliation record. A conflicting reconciliation for the same pair MUST NOT silently replace the existing record.

## Determinism

Canonical serialization and reconciliation identity MUST be deterministic.

## Missing outcome

A dispatch without an observed outcome produces `OUTCOME_MISSING`. This is an observation, not a release failure and not a new eligibility decision.

## Non-responsibilities

Retry policy, release execution, release decisioning, verification, authorization, eligibility creation, and automatic remediation remain outside P5-07.
