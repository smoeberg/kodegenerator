# P5-08 Release Remediation Architecture

## Status

Proposed implementation boundary for Phase 5.

## Purpose

P5-08 consumes the immutable observational result produced by P5-07 and translates a reconciled release state into an explicit remediation plan. It does not execute the remediation.

## Input

- `ReleaseReconciliationRecord` from P5-07.
- A deterministic remediation policy supplied to P5-08.

## Output

An immutable `ReleaseRemediationPlan` describing the next permitted action, or that no action is permitted.

Allowed actions:

- `NO_ACTION` — reconciliation is healthy or no remediation is authorized.
- `RETRY` — a retry is explicitly permitted by policy.
- `ESCALATE` — the state requires external/manual handling.
- `BLOCK` — remediation is prohibited by policy or safety constraints.

## Boundary

P5-08 MUST NOT:

- execute a release;
- dispatch or retry a release itself;
- modify a dispatch, outcome, or reconciliation record;
- create or evaluate release eligibility;
- perform verification;
- create or modify authorization;
- silently repair mismatched provenance;
- mutate upstream records;
- invent missing outcomes.

P5-08 is a decision-to-remediation-plan boundary, not an execution boundary.

## Safety rules

- `RECONCILED` MUST produce `NO_ACTION` by default.
- `OUTCOME_MISSING` MUST NOT automatically become `RETRY`; retry requires explicit policy authorization.
- `MISMATCH` MUST NOT automatically become `RETRY`; the default action is `ESCALATE` or `BLOCK` according to explicit policy.
- P5-08 MUST preserve the complete upstream identity chain in the plan.
- Unknown reconciliation statuses MUST fail closed.

## Determinism

For identical reconciliation identity, policy identity, and policy version, the same logical remediation plan MUST be produced.

## Immutability

`ReleaseRemediationPlan` MUST be immutable after construction.

## Idempotency

Repeated planning for the same reconciliation/policy pair MUST return the same logical plan. A later policy version constitutes a new planning input rather than mutating the previous plan.

## Separation of concerns

P5-07 observes and reconciles. P5-08 plans remediation. A later execution boundary, if required by the Phase 5 architecture, performs the actual action.
