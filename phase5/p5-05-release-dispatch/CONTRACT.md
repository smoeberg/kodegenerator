# P5-05 — Release Dispatch

## Purpose

P5-05 is the downstream release-dispatch boundary. It consumes the immutable P5-04 `FinalizationRecord` and creates a release-dispatch record for downstream release infrastructure.

Flow:

`P5-00 → P5-01 → SUBMITTED → P5-02 → P3-20 → P5-03 → P5-04 → P5-05`

P5-05 does not evaluate the work product. It does not verify anything and it does not decide release eligibility. It only dispatches an already-finalized, release-eligible result.

## Preconditions

P5-05 MUST require:

- a P5-04 finalization record;
- `state == FINALIZED`;
- verifier identity `p3-20` preserved from the upstream record;
- `disposition == RELEASE_ELIGIBLE`;
- a non-empty `finalization_fingerprint`;
- a non-empty `outcome_fingerprint`;
- the complete upstream identity chain preserved by P5-04.

A `RELEASE_BLOCKED` finalization MUST never be dispatched.

## Normative behavior

A successful dispatch produces an immutable `ReleaseDispatchRecord` containing:

- a unique dispatch identifier;
- the source finalization fingerprint;
- the upstream outcome fingerprint;
- request, submission, contract, handoff, and decision fingerprints;
- the P3-20 verifier identity;
- dispatch state and timestamp.

Repeated dispatch of the same finalization fingerprint is idempotent and MUST return the original dispatch record. A different dispatch id supplied for the same finalization MUST NOT create a competing dispatch.

## Authority boundary

P5-05 MUST NOT:

- create or modify a `VerificationDecision`;
- inspect acceptance criteria;
- inspect artifacts to determine pass/fail;
- promote evidence to authoritative evidence;
- change the P3-20 decision;
- derive `RELEASE_ELIGIBLE` from anything other than the P5-04 disposition;
- convert `RELEASE_BLOCKED` into a dispatchable state;
- mutate the P5-04 record.

P5-05 is a **consumer of release authority**, not a source of release authority.

## Side-effect boundary

The core dispatcher creates an immutable dispatch record only. External publication, deployment, transport, and other side effects are represented by a downstream sink/adapter and are outside the core authority decision.

A sink MUST receive the already-created immutable dispatch record; it MUST NOT receive the original artifact or be asked to make a release decision.
