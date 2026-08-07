# P3-20 — Independent Audit & Test Verification Gate

## Purpose

P3-20 is the independent quality gate between specialist-agent delivery and release eligibility.

It does **not** trust a specialist agent's own PASS claim. It evaluates the delivered product and its evidence against the exact dispatch and compiled contract that authorized the work.

## Pipeline

```text
Requirements
    ↓
P3-18 Contract Compiler
    ↓
P3-19 Distribution / Routing
    ↓
Specialist Agent
    ↓
Product + Evidence
    ↓
P3-20 Independent Verification Gate
    ↓
PASS / FAIL + evidence
```

## Verification invariants

1. The dispatch package fingerprint is preserved.
2. The exact specialist contract fingerprint is preserved.
3. Delivered outputs are restricted to contract-permitted outputs.
4. Evidence is bound to the exact package, contract, dispatch and artifact fingerprints.
5. Required evidence classes are present and explicitly passed:
   - `test`
   - `audit`
   - `security`
   - `provenance`
6. Any missing, failed or mismatched evidence produces `FAIL`.
7. Verification is deterministic for identical inputs.
8. No LLM call, prompt rewriting, architecture selection or policy invention occurs inside the gate.

## VerificationResult

A verification result contains:

- verification identity
- package fingerprint
- contract fingerprint
- dispatch fingerprint
- artifact fingerprint
- individual verification checks
- evidence IDs
- explicit failures
- deterministic result fingerprint

`status` is exactly `PASS` or `FAIL`. A PASS cannot contain failures; a FAIL must contain at least one failure.

## Security model

The gate is fail-closed. Evidence that cannot be bound to the exact delivery context is not accepted as proof. A specialist cannot make its own output eligible for release merely by declaring success.

## Scope boundary

P3-20 verifies the product/evidence boundary and emits the authoritative verification result. It deliberately does not become an autonomous project architect or agent router. Those responsibilities remain with the earlier contract and distribution stages.
