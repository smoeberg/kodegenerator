# P3-21 — Verification Execution Adapters

## Purpose

P3-21 supplies the execution boundary that turns real tool results into P3-20 `Evidence` objects. It does not make architectural decisions and does not replace the independent verification gate.

## Boundary

```text
Specialist product
      |
      v
P3-20 verification contract
      |
      v
P3-21 execution adapters
      |
      +--> tests
      +--> audit
      +--> security
      +--> provenance
      |
      v
bound Evidence
      |
      v
P3-20 independent PASS / FAIL
```

## Rules

1. Commands are immutable and supplied by trusted application code.
2. `shell=False` is mandatory; user text is never interpolated into commands.
3. Every execution is bound to package, contract, dispatch and artifact fingerprints.
4. Adapter identity is deterministic.
5. Tool output is not treated as an architectural instruction and is not passed to an LLM by this layer.
6. Execution failure becomes failed evidence; infrastructure failures (invalid workspace, timeout, inability to start) raise an execution error rather than being reported as PASS.
7. P3-20 remains the only authority for the final PASS/FAIL decision.

## Initial adapters

- pytest — test evidence
- compileall — architecture evidence
- bandit — security evidence
- git rev-parse HEAD — provenance evidence

The adapters are deliberately small. Future adapters can wrap additional deterministic tools without changing the P3-20 contract.
