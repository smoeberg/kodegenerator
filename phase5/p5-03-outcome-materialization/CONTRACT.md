# P5-03 — Outcome Materialization & Finalization

## Purpose

P5-03 is the post-verification integrity boundary. It consumes an already-bound
P5-02 handoff and materializes an immutable outcome record for downstream
runtime consumers.

The flow is:

`P5-00 Contract → P5-01 Execution → SUBMITTED → P5-02 Handoff → P3-20 Decision → P5-03 Outcome`

## Authority

- Agent: creates work product and candidate evidence.
- P5-01: executes and submits.
- P5-02: binds and routes the verification request and binds the returned decision.
- P3-20: alone creates the authoritative verification decision.
- P5-03: materializes that authoritative decision into a stable outcome record.

P5-03 MUST NOT verify, re-verify, reinterpret, or manufacture a decision.

## Required invariants

1. The supplied handoff must be a final P5-02 state: `VERIFIED_PASSED` or `VERIFIED_FAILED`.
2. A final handoff must contain a P3-20 decision.
3. Decision verifier must be exactly `p3-20`.
4. Decision submission ID, submission fingerprint, and contract fingerprint must match the handoff request.
5. The materialized outcome preserves the exact P3-20 decision fingerprint when available.
6. P5-03 is idempotent for the same immutable handoff fingerprint.
7. P5-03 never creates `CriterionResult` or `VerificationDecision`.
8. P5-03 never upgrades candidate evidence to authoritative evidence by itself.
9. `PASSED` and `FAILED` are copied from the authoritative P3-20 decision; they are not independently evaluated.

## Outcome states

```text
VERIFIED_PASSED ──> OUTCOME_MATERIALIZED
VERIFIED_FAILED ──> OUTCOME_MATERIALIZED
```

The materializer does not introduce a new verification judgment. `OUTCOME_MATERIALIZED`
means only that an already-authoritative P3-20 result has been durably represented.

## Downstream boundary

Consumers may use the outcome record to decide whether a subsequent release,
distribution, or publication operation is eligible. Such a consumer is outside
P5-03 and must not treat materialization itself as a new verification authority.

## Failure semantics

Missing final state, missing decision, wrong verifier, or identity mismatch is a
hard integrity error. There is no fallback outcome and no conversion of an
unknown/transport condition into `FAILED`.
