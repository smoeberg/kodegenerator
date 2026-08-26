# Phase 4 Council Runtime Contract

This contract makes Council deliberation and Anti-Tube observations durable
without granting the Council either authority or execution capability.

## Invariants

1. Every session is bound immutably to an `organization_id`,
   `context_packet_id`, hypothesis revision, and workspace revision.
2. Reads and writes are organization-scoped. A cross-organization lookup is
   indistinguishable from a missing session.
3. Session updates require the exact `state_version`; stale writers fail with
   an optimistic-concurrency conflict.
4. Evidence IDs are bound immutably to their content digest and revisions.
   Authority readiness must use the repository-derived evidence revision map.
5. An execution failure is accepted only when all provenance fields match the
   stored session. Mismatches fail closed before state is written.
6. Failure ingestion is idempotent by `event_id`, and an `execution_id` cannot
   be reused with changed failure content. Redelivery cannot increment
   Anti-Tube history or produce duplicate downstream work.
7. Aggregate changes and their outbox events commit in the same transaction.
8. `PIVOT_REQUIRED`, `HUMAN_REQUIRED`, environment halt, and policy escalation
   are explicit signals. None directly calls Authority or Execution.
9. There is no weak Council mode. Missing required review capacity is a future
   orchestrator start failure, not a reduction of the gate.

## Durable records

| Record | Purpose |
| --- | --- |
| `council_sessions` | Aggregate snapshot, immutable provenance, OCC version |
| `council_disputes` | Formal dispute state and resolving evidence |
| `council_votes` | One vote per organization/session/round/agent |
| `council_evidence_bindings` | Immutable evidence-to-revision proof |
| `council_failure_observations` | Idempotent AI-4 failures and Anti-Tube result |
| `council_outbox_events` | Transactional downstream signals |

## AI-4 failure event

`ExecutionFailedEvent` is the canonical boundary from execution to Council. It
contains the organization, session, hypothesis and revisions, context packet,
execution ID, strategy fingerprint, and normalized failure. Its deterministic
ID is derived from the immutable execution/provenance identity.

The handler validates the event against the stored session, replays prior
observations for the same organization/session/fingerprint into
`AntiTubeTrigger`, evaluates the new failure, and commits both the observation
and exactly one outbox event.

| Anti-Tube action | Outbox event |
| --- | --- |
| `RETRY` | `COUNCIL_FAILURE_OBSERVED` |
| `PIVOT_REQUEST` | `COUNCIL_PIVOT_REQUIRED` |
| `HALT_ENVIRONMENT` | `COUNCIL_ENVIRONMENT_HALT_REQUIRED` |
| `POLICY_ESCALATION` | `COUNCIL_POLICY_ESCALATION_REQUIRED` |

## Recovery semantics

After a process restart, the runtime rehydrates the hypothesis, session state,
rounds, disputes, votes, and history from the database. Anti-Tube state is not
trusted from process memory: prior durable failure observations are replayed in
order before evaluating a new event. Pending outbox events remain publishable
until explicitly marked published.

## Deliberate next boundary

`CouncilOrchestrator` will consume this repository and event contract. It may
select roles and call model providers, but it must only return a
`DecisionReadiness`. Risk derivation, required-role enforcement, and the
Decision Cockpit consumer are separate follow-up changes; no placeholder here
silently weakens Authority's existing fail-closed gate.
