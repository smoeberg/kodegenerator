# P5-04 — Release Finalization & Publication Gate

P5-04 is the terminal runtime consumer of the authoritative P5-03 outcome.

It maps:

- `PASSED` → `RELEASE_ELIGIBLE`
- `FAILED` → `RELEASE_BLOCKED`

It preserves the full upstream identity chain:

`contract → submission → handoff → P3-20 decision → outcome → finalization`

No publication, deployment, distribution, or external side effect occurs in
P5-04. A downstream release subsystem may consume the immutable finalization
record later.

## Authority rule

P5-04 never verifies. It only consumes the result already authorized by
P3-20 and materialized by P5-03.
