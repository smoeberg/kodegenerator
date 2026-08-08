# AI-7 — Agent Orchestrator & Reflexion Loop Contract

## Status

First contract gate. This defines immutable models, safety invariants, and
contract tests. It deliberately does not implement a smart or autonomous loop.

## Boundary

```text
AI-5 Outcome
      ↓
AI-7 Orchestrator
      ↓
AI-6 Planner
      ↓
AI-3 Authority
      ↓
AI-4 Execution
      ↓
AI-5 Outcome
      ↺
```

AI-7 only coordinates this sequence:

- AI-6 is the sole boundary that decides or proposes continuation work.
- AI-3 is the sole boundary that issues authority decisions.
- AI-4 is the sole boundary that invokes execution adapters.
- AI-5 is the sole boundary that records outcomes and state transitions.
- AI-7 must not reproduce, override, or mutate any of those decisions.

`CONTINUE` means only “hand the unchanged `PlanRequest` to AI-6.” It never
means that AI-7 has approved or initiated another execution.

## Correlation and identity

Every run has a caller-supplied, non-empty `run_id`. Every iteration has a
deterministic `iteration_id` derived from the `run_id`, one-based iteration
number, and retry count. The retry count must equal the iteration number minus
one, preventing either safety counter from being reset independently.

The plan attempt, orchestration retry count, and iteration identity must agree.
The `run_id` and `iteration_id` are preserved across an AI-6 handoff.

## Bounded loop

Both ceilings are explicit and finite:

- `max_depth >= 1`
- `max_retries >= 0`

There are no implicit retries. AI-7 stops before producing an AI-6 handoff
when either ceiling has been reached. AI-6 may impose a stricter continuation
policy; AI-7 does not weaken it.

## STOP states

All states except `ACTIVE` are terminal:

- `COMPLETED`
- `AUTHORITY_DENIED`
- `AUTHORITY_UNVERIFIED`
- `OUTCOME_UNKNOWN`
- `DUPLICATE_OUTCOME`
- `DEPTH_LIMIT_REACHED`
- `RETRY_LIMIT_REACHED`

An AI-3 `DENY`, a missing or malformed authority decision, and an AI-5
`UNKNOWN` or unrecognized outcome always stop fail closed. A replayed or
previously processed outcome also stops; it can never create another planner
handoff.

## Outcome integrity and duplicate protection

AI-7 carries the exact immutable AI-5 `OutcomeRecord` inside the exact
immutable AI-6 `PlanRequest`. It neither copies with modified fields nor
produces transitions. Processed outcome IDs are unique within the run, and a
previously processed current outcome terminates as `DUPLICATE_OUTCOME`.

## Negative authority

The AI-7 public contract contains no execution engine, adapter, authority
request, or authority engine. Its only non-terminal output is a
`PlannerHandoff` whose boundary is fixed to `AI-6`, and that handoff is marked
neither executable nor authoritative.

## First-gate acceptance criteria

- Immutable models and deterministic iteration identity.
- Explicit `CONTINUE` and `STOP` directives.
- Explicit terminal states and fail-closed unknown handling.
- Bounded loop depth and bounded retry count.
- Stable `run_id` correlation through the AI-6 handoff.
- Duplicate and replayed outcomes cannot continue.
- Denied or unverifiable authority terminates.
- AI-7 cannot execute, issue authority, or mutate outcomes.
- Any continuation is routed through AI-6 with the original `PlanRequest`.
- Contract tests cover every invariant above.
