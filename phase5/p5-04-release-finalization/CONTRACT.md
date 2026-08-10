# P5-04 — Release Finalization & Publication Gate

## Purpose

P5-04 is the terminal runtime boundary for a P5 work product after P5-03 has materialized the authoritative P3-20 verification outcome.

Flow:

`P5-00 → P5-01 → SUBMITTED → P5-02 → P3-20 → P5-03 → P5-04`

P5-04 turns an immutable `OutcomeRecord` into an immutable finalization record that tells downstream runtime infrastructure whether the product is eligible for release. It does not evaluate the work and does not become a verifier.

## Preconditions

P5-04 MUST require:

- a P5-03 outcome record;
- `state == OUTCOME_MATERIALIZED`;
- verifier identity `p3-20`;
- a non-empty outcome fingerprint;
- a value of `PASSED` or `FAILED`;
- stable contract, submission, handoff, and decision fingerprints.

## Normative behavior

For `PASSED`, P5-04 produces a finalization record with `release_eligible=True`. For `FAILED`, it produces a terminal finalization record with `release_eligible=False`.

The finalization record preserves all upstream fingerprints and is immutable. Repeated finalization of the same outcome fingerprint is idempotent and must return the original record rather than create a competing finalization.

## Authority boundary

P5-04 MUST NOT:

- create or modify a `VerificationDecision`;
- inspect acceptance criteria to decide pass/fail;
- promote candidate evidence to authoritative evidence;
- change the P3-20 decision;
- infer a pass from artifact contents;
- turn a failed outcome into a releasable outcome;
- silently accept a changed outcome fingerprint.

P5-04 is a **consumer of authority**, not a source of authority.

## Release boundary

`release_eligible=True` is a runtime disposition derived solely from the already-authoritative P3-20 outcome represented by P5-03. Actual publication, distribution, deployment, or external side effects are outside P5-04.
