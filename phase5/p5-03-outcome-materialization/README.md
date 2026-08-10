# P5-03 — Outcome Materialization & Finalization

P5-03 is the post-verification boundary. It consumes a completed P5-02 handoff and materializes the authoritative P3-20 decision as an immutable outcome record.

It does not verify, re-run predicates, create decisions, or promote candidate evidence.

## Flow

`P5-00 → P5-01 → SUBMITTED → P5-02 → P3-20 → P5-03`

## Modules

- `outcome_models.py` — immutable outcome record and integrity fingerprint
- `materializer.py` — idempotent materialization engine
- `CONTRACT.md` — normative boundary
- `tests/test_materializer.py` — authority, identity and idempotency gates

The module names are deliberately unique because P5-00/P5-02 use slice-local modules and pytest runs the complete repository as one import environment.
