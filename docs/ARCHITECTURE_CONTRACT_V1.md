# Architecture Contract v1

Machine-readable architecture contract for DOR code generation and validation.

## Artifacts

| Path | Purpose |
| --- | --- |
| [`docs/schemas/architecture-contract-v1.schema.json`](schemas/architecture-contract-v1.schema.json) | Normative JSON Schema for the contract |
| [`docs/schemas/architecture-verification-result-v1.schema.json`](schemas/architecture-verification-result-v1.schema.json) | Normative result schema from contract evaluation |
| [`docs/schemas/examples/architecture-contract-v1.hexagonal-python.example.yaml`](schemas/examples/architecture-contract-v1.hexagonal-python.example.yaml) | Minimal hexagonal Python example |

## Purpose

The architecture contract is the boundary between human-approved design and automated implementation/verification.

Downstream agents may generate or patch code only against an **approved** contract. Verification produces an independent result bound to:

- `contract_id`
- `contract_version`
- `contract_fingerprint`

## Evaluation rules (fail-closed)

1. Only contracts with `status: approved` (and matching approval proof) may authorize codegen/execution scope.
2. `content_fingerprint` is SHA-256 over canonical contract content **excluding** approval workflow metadata.
3. Verification aggregation:
   - any `block` check with status `FAIL` → overall `FAIL`
   - verifier crash / missing required evidence → overall `ERROR` (consumers treat as non-PASS)
   - `warn` alone does not force `FAIL` unless policy says otherwise
4. Patch/codegen scope is constrained by `scope.allowed_paths` minus `scope.denied_paths` when present.
5. The independent verification gate (P3-20) remains the sole issuer of authoritative PASS/FAIL for delivery.

## Relation to existing domain model

`domain/architecture_contract.py` remains the Phase 3 foundation object. Architecture Contract v1 is the richer, evaluable schema for structural rules, interfaces, constraints, and quality gates.

Migration path:

1. Validate documents against the v1 JSON Schema
2. Parse into a domain/runtime model with fingerprinting
3. Implement evaluators starting with `dependency_rules` and `forbid_pattern`
4. Emit `architecture-verification-result-v1` into the verification gate

## Explicit non-goals (v1 schema only)

This commit adds schemas and an example only. It does **not**:

- implement a full evaluator
- replace `domain/architecture_contract.py`
- authorize autonomous multi-agent execution
