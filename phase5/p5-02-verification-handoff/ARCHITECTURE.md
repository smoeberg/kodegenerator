# P5-02 — Verification Handoff & Evidence Binding Architecture

**Status:** Architecture only — implementation is intentionally not started.

P5-02 is the boundary between AI execution and independent verification. P5-01 ends at `SUBMITTED`. P5-02 binds that immutable submission to the P5-00 contract and constructs a deterministic handoff to P3-20, which remains the sole verification authority.

## Pipeline

```text
P5-00 Contract → P5-01 Execution → SUBMITTED
                                      │
                                      ▼
                         P5-02 Verification Handoff
                         ├─ bind contract + submission
                         ├─ freeze evidence set
                         ├─ construct VerificationRequest
                         └─ route only to P3-20
                                      │
                                      ▼
                              P3-20 Verification
                                      │
                                      ▼
                             VerificationDecision
                                      │
                                      ▼
                         P5-02 binds + records result
```

## Inputs

- immutable `AIWorkProductContract` from P5-00;
- immutable `WorkProductSubmission` from P5-01;
- P3-20 verification authority identity/configuration.

The submission must match `contract_fingerprint` and be in `SUBMITTED` state.

## VerificationRequest

The deterministic request contains at least `request_id`, `submission_id`, `submission_fingerprint`, `contract_fingerprint`, contract and submission snapshot/reference, required artifacts, acceptance criteria, verification procedure identity/version, candidate-evidence references, repository-state identity, creation timestamp, and verifier identity `p3-20`.

The request is canonically fingerprinted before dispatch.

## Evidence authority

**Candidate evidence** is created by the agent and remains non-authoritative. P5-02 may transport and bind it, but may never upgrade its authority.

**Governed evidence** is created or accepted only by P3-20. P5-02 may record and bind it, but may not manufacture it.

## Responsibilities

P5-02 MUST reject submissions not bound to the supplied contract or not in `SUBMITTED` state; freeze exact contract/submission fingerprints; preserve candidate evidence without upgrading authority; construct a deterministic verification request; route only to P3-20; bind returned `VerificationDecision` to the exact submission and contract; reject other verifier identities; preserve the decision as immutable evidence; and make the handoff auditable through append-only events.

P5-02 MUST NOT execute the agent, modify the work product/contract, decide acceptance criteria, independently create `CriterionResult` or `VerificationDecision`, upgrade evidence authority, accept another verifier, infer success from CI/agent claims/artifact presence, or bypass P3-20.

## State machine

```text
SUBMITTED → VERIFICATION_READY → VERIFICATION_DISPATCHED
                                      │
                                      ├→ VERIFICATION_REJECTED
                                      │
                                      ▼
                               VERIFICATION_RETURNED
                                      │
                                      ├→ VERIFIED_PASSED
                                      └→ VERIFIED_FAILED
```

`VERIFIED_PASSED` and `VERIFIED_FAILED` are projections of the P3-20 `VerificationDecision`, never decisions made by P5-02.

## Failure semantics

Malformed/mismatched submissions are rejected before dispatch. A verifier response is rejected when verifier identity, submission ID/fingerprint, contract fingerprint, decision identity, or criterion identity does not match.

**Transport failure is not verification failure.** It remains a handoff failure and must never become `passed=False`.

## Idempotency

Handoff identity is `(submission_id, submission_fingerprint, contract_fingerprint)`. Repeated handoffs for the same immutable submission must not create divergent verification identities. A changed submission fingerprint is a new verification subject.

## Authority separation

```text
Agent   → work + candidate evidence
P5-01   → execute + submit
P5-02   → bind + route verification
P3-20   → independently verify + decide
P5-02   → bind + record authoritative decision
```

P5-02 is an orchestration/integrity boundary, not a verification authority.

## Implementation boundary

```text
phase5/p5-02-verification-handoff/
├── ARCHITECTURE.md
├── contract.py
├── models.py
├── handoff.py
├── fingerprinting.py
└── tests/
    ├── test_handoff.py
    ├── test_identity_binding.py
    ├── test_authority_boundary.py
    └── test_idempotency.py
```

Implementation must reuse the P5-00 domain model and must not fork P3-20.

## Acceptance gates

Tests must prove contract/submission fingerprint binding, `SUBMITTED` prerequisite, candidate evidence remains candidate, only P3-20 can supply a verification decision, mismatched decisions are rejected, transport failure is distinct from verification failure, identical handoffs are idempotent, no P5-02 path can independently issue PASS/FAIL, and full CI remains green.

## Architectural decision

**P5-02 = Verification Handoff & Evidence Binding.** P5-00 defines the normative work-product verification protocol and P3-20 remains the authority. P5-02 makes the transition from `SUBMITTED` execution output to independently verified result explicit, traceable, immutable, and safe.
