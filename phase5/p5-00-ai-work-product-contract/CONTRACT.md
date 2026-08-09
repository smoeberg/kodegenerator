# P5-00 — AI Work Product Contract & Verification Protocol

## Normative principle

> A completion report is a claim, not a completion event. A work product is accepted only when the submitted artifact state satisfies its immutable contract through independent verification.

## Authority model

The agent may inspect, implement, test, and submit. It may provide candidate evidence, but it cannot create authoritative verification evidence or issue PASS/FAIL.

Only P3-20 may issue `VerificationDecision.passed` and the corresponding terminal lifecycle event.

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

The canonical contract is fingerprinted before dispatch. The fingerprint is immutable for the dispatched work.

## Submission

`WorkProductSubmission` binds a submission identity to:

- exact contract fingerprint
- agent identity
- repository identity, revision and tree fingerprint
- submitted artifact manifest and fingerprints
- candidate evidence
- submission timestamp

A submission does not contain an authoritative delivery state.

## Lifecycle

Delivery state is derived exclusively from append-only `LifecycleEvent` records:

`DRAFT -> DISPATCHED -> IN_PROGRESS -> SUBMITTED -> VERIFYING -> PASSED | FAILED`

The runtime/agent may drive operational transitions through submission. Only P3-20 may enter `VERIFYING` and resolve `PASSED` or `FAILED`.

A failed submission is terminal. A retry requires a new submission identity and new artifact/evidence fingerprints. Previous decisions are never rewritten.

## Verification

Verification is fail-closed:

1. Contract fingerprint must match exactly.
2. Repository identity, revision and tree fingerprint must be present.
3. Every required artifact must exist in the governed repository state.
4. Submitted artifact fingerprints must match governed repository fingerprints.
5. Candidate evidence is never authoritative evidence.
6. Every acceptance criterion is evaluated independently.
7. Missing governed evidence fails the criterion.
8. Missing verifier or non-P3-20 authority is rejected.
9. Any mandatory failed criterion yields overall FAIL.
10. Only P3-20 can issue the final decision.

## Security invariants

- Contract mutation after dispatch is invalid.
- Artifact mutation after submission is detectable by fingerprint mismatch.
- Evidence mutation after submission is detectable by evidence fingerprint mismatch when governed evidence is materialized.
- Agent-generated PASS is not accepted as a verification decision.
- Completion summaries cannot substitute for required artifacts.
- Missing required artifacts fail closed.
