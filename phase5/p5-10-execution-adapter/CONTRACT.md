# P5-10 — Execution Adapter Contract

P5-10 is the controlled side-effect boundary after P5-09. It accepts an immutable `ExecutionRequest` and delegates exactly one authorized operation to an adapter.

Flow: `P5-08 Resolution → P5-09 Execution Boundary → P5-10 Execution Adapter → controlled side effect`

## Boundary

P5-10 MUST:

- accept only a valid immutable execution request;
- require explicit adapter identity and authorization;
- validate that the adapter supports the requested execution kind;
- invoke the adapter exactly once for an accepted request;
- return an immutable execution result;
- preserve request identity and provenance in the result;
- fail closed before invocation when validation or authorization fails.

## Side effects

P5-10 is the first P5 boundary permitted to invoke an external adapter. The adapter performs the actual external operation.

P5-10 MUST NOT perform retry scheduling, deployment, publication, verification, reconciliation, or remediation itself.

P5-10 MUST NOT silently retry an adapter call. An adapter failure is returned as a failed execution result and MUST NOT be converted into success.

## Authorization

Execution authorization MUST be explicit. A missing adapter, missing adapter identity, unauthorized adapter, or unsupported execution kind MUST fail closed and MUST produce no adapter invocation.

Authorization MUST NOT be inferred from the P5-08 disposition alone.

## Request integrity

Request identity, resolution identity, resolution fingerprint, disposition, and execution kind MUST be passed to the adapter without reinterpretation. P5-10 MUST NOT mutate the request.

## Idempotency

The same `request_id` MUST identify the same execution request. P5-10 MUST provide the request identity to the adapter so the downstream adapter can enforce idempotency where supported.

P5-10 MUST NOT manufacture a second request identity for the same input.

## Failure semantics

Validation/authorization failures occur before side effects. Adapter failures are represented as failed execution results and preserve the original request identity. Exceptions from the adapter MUST NOT be swallowed and converted to successful results.

## Immutability and determinism

Execution requests and execution results MUST be immutable. Validation and result construction MUST be deterministic for identical request, adapter policy, and adapter outcome.

## Non-responsibilities

P5-10 does not decide whether a release should happen, change a P5-08 disposition, grant authority, alter verifier identity, or mutate P5-04–P5-09 records.