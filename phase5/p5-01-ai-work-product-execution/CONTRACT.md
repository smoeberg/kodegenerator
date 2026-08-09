# P5-01 — AI Work-Product Execution

## Purpose

P5-01 is the execution boundary that consumes an immutable P5-00
`AIWorkProductContract`, dispatches an agent execution, and records the
result as a submitted work product.

P5-01 does **not** decide whether the work product is correct.

## Normative boundary

The execution runtime owns:

1. binding execution to the exact P5-00 contract fingerprint;
2. assigning an execution identity and agent identity;
3. emitting `DISPATCHED` as the runtime actor;
4. allowing the agent to enter `IN_PROGRESS`;
5. accepting only a `WorkProductSubmission` bound to the same execution,
   agent, and contract fingerprint;
6. emitting `SUBMITTED` as the agent actor.

The execution runtime must stop at `SUBMITTED`.

## Verification boundary

P5-01 MUST NOT:

- create `PASSED` or `FAILED` lifecycle events;
- issue a `VerificationDecision`;
- treat agent claims as governed evidence;
- alter the P5-00 contract;
- silently accept a submission with a different contract fingerprint;
- silently accept a submission from a different agent or execution identity.

Verification remains the P5-00/P3-20 governed boundary.

## Agent interface

An agent is integrated through the small `AgentExecutor` protocol:

```text
execute(ExecutionContext) -> WorkProductSubmission
```

The returned submission is treated as untrusted output and is checked only
for execution-bound identity at this layer. Artifact completeness, governed
evidence, repository-state equality, acceptance criteria, and the final
verification decision remain outside P5-01.

## Import boundary

P5-00 intentionally uses a hyphenated slice directory without an
`__init__.py`. P5-01 therefore uses the explicit `p5_00_loader.py` package
loader and does not reintroduce a pytest-hostile top-level initializer.
