# P5-00 — AI Work Product Contract & Verification Protocol

## Status

**Normative and implementation-complete for P5-00.** P5-01 must not be dispatched against this protocol until its contract is migrated to these objects and gates.

## Normative principle

> A completion report is a claim, not a completion event. A work product is accepted only when the submitted artifact state satisfies its immutable contract through independent verification.

## Authority model

The agent may inspect, implement, test, and submit. It may provide candidate evidence, but it cannot create authoritative verification evidence or issue PASS/FAIL.

The verification runtime may enter `VERIFYING`. Only P3-20 may issue `VerificationDecision.passed` and the corresponding terminal lifecycle event.

## Contract

`AIWorkProductContract` binds:

- contract identity and version
- product type and location
- intent, inputs and outputs
- required artifacts
- acceptance criteria
- verification procedure
- regression requirements
- required capabilities
- authority boundaries
- forbidden actions and outputs

A contract must declare at least one required artifact and one acceptance criterion. Every acceptance criterion names a stable ID, machine-verifiable predicate, evidence source and `p3-20` verifier.

The canonical contract is fingerprinted before dispatch. The fingerprint is immutable for the dispatched work. Every lifecycle event carries that fingerprint, so a later event cannot silently switch contracts.

## Submission

`WorkProductSubmission` binds a submission identity to:

- exact contract fingerprint
- agent identity
- repository identity, revision, cleanliness and tree fingerprint
- submitted artifact manifest and fingerprints
- candidate evidence
- submission timestamp

A submission does not contain an authoritative delivery state. Its fingerprint covers all submitted content, so later mutation is detectable.

## Lifecycle

Delivery state is derived exclusively from append-only `LifecycleEvent` records:

`DRAFT → DISPATCHED → IN_PROGRESS → SUBMITTED → VERIFYING → PASSED | FAILED`

- DOR runtime dispatches the immutable contract binding.
- Agent/runtime may advance operational work through `IN_PROGRESS` and `SUBMITTED`.
- Verification runtime may start `VERIFYING`.
- Only P3-20 may resolve `PASSED` or `FAILED`.
- Terminal states cannot transition further.

A failed submission is terminal. A retry requires a new submission identity and new artifact/evidence fingerprints. Previous decisions are never rewritten.

## Verification

Verification is fail-closed:

1. Contract fingerprint must match exactly.
2. Repository identity, revision and tree fingerprint must be present.
3. If a governed repository snapshot is supplied, it must exactly equal the submitted snapshot.
4. Every required artifact must be submitted.
5. Submitted artifact type and location must match the contract.
6. Submitted artifact fingerprints must match governed repository fingerprints.
7. Candidate evidence is never authoritative evidence.
8. Governed evidence IDs and payload fingerprints must be unique and must match the verifier's materialized evidence fingerprints.
9. Governed evidence may reference only declared acceptance criteria.
10. Every acceptance criterion is evaluated independently.
11. Missing governed evidence fails the criterion.
12. Missing predicate or non-P3-20 authority is rejected/fails closed.
13. Every failed required artifact yields overall FAIL.
14. Every failed mandatory acceptance criterion yields overall FAIL; optional criteria may fail without failing the whole product.
15. Only P3-20 can issue the final decision.

## Security invariants

- Contract mutation after dispatch is invalid.
- Every lifecycle event remains bound to the original contract fingerprint.
- Artifact mutation after submission is detectable by fingerprint mismatch.
- Repository revision/tree changes after submission are detectable by governed repository-state comparison.
- Evidence mutation after materialization is detectable by evidence fingerprint mismatch.
- Agent-generated PASS is not accepted as a verification decision.
- Completion summaries cannot substitute for required artifacts.
- Missing required artifacts fail closed.
- Verification decisions bind to the exact submission fingerprint and contract fingerprint.
- Lifecycle state cannot be supplied or mutated as an agent field.

## Required proof

The P5-00 test suite covers the positive path and adversarial cases for:

- contract fingerprint mismatch
- missing required artifacts
- artifact fingerprint mismatch
- artifact metadata mismatch
- candidate versus governed evidence
- missing governed evidence
- missing predicates
- changed governed evidence
- changed repository state
- non-P3-20 verification authority
- contract-bound append-only lifecycle transitions
- verification-runtime entry into `VERIFYING`
- P3-20-only terminal resolution
- terminal failed submissions
