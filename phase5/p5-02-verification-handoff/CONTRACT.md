# P5-02 — Verification Handoff & Evidence Binding

## Purpose

P5-02 is the integrity boundary between P5-01 execution and independent P3-20 verification.

`P5-01` ends at `SUBMITTED`. P5-02 accepts only a submitted work product, freezes its exact contract/submission identity, creates a deterministic verification request, routes it to `p3-20`, and binds the returned authoritative decision.

## Authority

- **Agent:** creates work product and candidate evidence.
- **P5-01:** executes and submits.
- **P5-02:** binds, routes, and records verification state.
- **P3-20:** independently verifies and alone creates `VerificationDecision` / `CriterionResult`.

P5-02 MUST NOT manufacture, infer, or upgrade verification authority.

## Required invariants

1. Submission `contract_fingerprint` equals the supplied P5-00 contract fingerprint.
2. The lifecycle evidence supplied to P5-02 derives to `SUBMITTED`.
3. The verification request targets exactly `p3-20`.
4. The request binds `submission_id`, `submission_fingerprint`, and `contract_fingerprint`.
5. Candidate evidence remains candidate evidence.
6. A returned decision must bind to the exact submission and contract fingerprints.
7. A non-`p3-20` verifier is rejected.
8. Transport failure is not represented as `passed=False`.
9. Repeated handoff for the same immutable subject reuses the same request identity.
10. P5-02 has no verification-decision factory and does not execute verification predicates.

## State projection

```text
VERIFICATION_READY
        |
        v
VERIFICATION_DISPATCHED
        |
        +--> VERIFICATION_REJECTED       (transport failure)
        |
        v
VERIFICATION_RETURNED
        |
        +--> VERIFIED_PASSED             (P3-20 decision)
        +--> VERIFIED_FAILED             (P3-20 decision)
```

`VERIFIED_PASSED` and `VERIFIED_FAILED` are projections of a P3-20 decision, not P5-02 decisions.

## Failure semantics

A malformed submission, wrong contract fingerprint, wrong verifier, or mismatched returned decision is rejected. A transport exception is explicitly distinct from a verification decision and cannot become `passed=False`.

## Implementation boundary

- `models.py` — immutable request/response/handoff models
- `fingerprinting.py` — canonical request/handoff fingerprints
- `handoff.py` — orchestration and integrity checks
- `p5_00_loader.py` — explicit P5-00 slice loader
- `tests/` — binding, authority, transport and idempotency gates

The implementation does not fork P3-20 or alter P5-00's normative verification engine.
