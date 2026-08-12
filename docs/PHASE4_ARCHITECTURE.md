# Phase 4 — EIRA Brain & Workforce Control Plane

**Status:** Canonical target architecture  
**Version:** 1.0  
**Date:** 2026-08-12

> This document supersedes earlier Phase 4 concepts based on a generic `ConversationEngine` / agent-conversation runtime. Those concepts are retained only as historical design context and are not the implementation target.

## 1. Purpose

Phase 4 provides the cognitive and workforce-control layer of the Digital Organization Runtime (DOR). It does **not** attempt to replace LibreChat as a conversational UI, nor does it duplicate the Phase 7 execution queue.

Phase 4 owns:

- persistent agent identity and workforce metadata;
- assignment semantics between agents and work;
- epistemic records: observations, claims, evidence and verification;
- materialized organizational knowledge state;
- verification policy and risk-driven consensus;
- integration boundaries to interaction surfaces and execution infrastructure.

## 2. Architectural boundary

```text
                         HUMAN
                           |
                           v
                     +-----------+
                     | LibreChat |
                     | Interaction|
                     |  Surface  |
                     +-----+-----+
                           |
                    Interactive mode
                           |
                           v
+-----------------------------------------------------------+
|                 EIRA CONTROL PLANE                        |
|                                                           |
|  Agent Registry   Assignment   Brain   Verification       |
|       |               |          |          Policy         |
+-------+---------------+----------+-------------------------+
                        |
                        v
                 Phase 7 Queue
                        |
                        v
                     Worker
                        |
                        v
                  Agent runtime
                        |
                        +---------> Brain

                    Autonomous mode
```

### Responsibility boundaries

| Component | Owns | Does not own |
|---|---|---|
| LibreChat | Human interaction, chat/session UX, conversational presentation | Agent identity, authority, durable organizational truth, background worker scheduling |
| Agent Registry | Agent identity, role, capabilities and lifecycle metadata | Worker process lifecycle |
| Assignment | Binding of work to an agent with execution/lease state | Compute process identity |
| Brain | Epistemic records and materialized knowledge state | Execution authority |
| Verification Policy | Rules for accepting or escalating claims | Runtime execution permissions |
| Phase 7 Queue | Durable jobs, leases, retries and worker ownership | Agent identity and epistemic truth |
| Phase 6 | Secure execution boundary | Epistemic consensus |
| Phase 5 | Work-product/release lifecycle | Agent cognition |

## 3. Fundamental invariants

The following are architectural invariants for Phase 4:

1. **Agent != Worker.** An agent is a persistent organizational identity; a worker is ephemeral compute.
2. **Agent != Assignment.** An assignment records a piece of work assigned to an agent.
3. **Agent identity survives worker failure.** A worker crash must not destroy or mutate the agent's identity.
4. **LibreChat is an interaction surface, not the autonomous worker runtime.** Background work uses the EIRA/Phase 7 execution path.
5. **Context != Knowledge.** `ContextPacket` controls bounded task context; Brain represents organizational knowledge.
6. **Knowledge confirmation != execution authority.** A confirmed claim never grants permission to execute an action.
7. **Authority remains governed by Phase 1–3 authority controls and `VerifiedAuthorityGrant`.**
8. **Deterministic verification is preferred over LLM consensus whenever deterministic evidence is sufficient.**
9. **High-risk or disputed claims may require quorum and/or human escalation.**
10. **Epistemic history is auditable.** Observations, claims, evidence and verification outcomes must not be silently overwritten.

## 4. Two execution modes

### Interactive

```text
Human -> LibreChat -> Agent -> EIRA Control Plane -> Brain / Authority
```

LibreChat is used when a human is interacting with an agent or when an agent needs to request human attention.

### Autonomous

```text
Trigger -> Assignment -> Phase 7 Queue -> Worker -> Agent -> Brain / Authority
```

Autonomous workers call model providers and tools directly through the EIRA execution path. LibreChat is not inserted into the worker loop merely to provide a chat session.

Both modes use the same EIRA-owned agent identities, governance, Brain and authority boundaries.

## 5. Agent, Assignment and Worker

### Agent

The existing `phase4/agent_registry` is the foundation for persistent agent identity, role and capability metadata. Phase 4 must extend that model only where required for the workforce-instance semantics; it must not introduce a parallel agent registry.

### Assignment

An Assignment represents the organizational relationship between work and an agent.

Minimum conceptual fields:

```text
assignment_id
 task_id
 agent_id
 state
 attempt
 lease information
 created_at
 updated_at
```

The Assignment is distinct from the Phase 7 queue message that transports/executes it.

### Worker

A Worker is ephemeral compute. Phase 7 already provides durable queue semantics, worker ownership, leases, retries and expired-lease recovery. Workers may execute assignments for many different agents over their lifetime.

This enables, for example:

```text
100 persistent agents
        |
        v
10-20 elastic workers
```

without requiring one permanent process per agent.

## 6. EIRA Brain

The Brain is an epistemic layer, not a general-purpose chat history store.

The conceptual flow is:

```text
Observation
    |
    v
Claim <---- Evidence
    |
    v
Verification
    |
    v
KnowledgeState
```

### Epistemic records

- **Observation:** an agent/system reports something it observed.
- **Claim:** a proposition asserted about a subject.
- **Evidence:** material supporting or contradicting a claim.
- **Verification:** an evaluation of the claim under a verification policy.
- **KnowledgeState:** the current materialized state derived from the epistemic record history.

The initial status vocabulary is:

```text
PROPOSED
DISPUTED
CONFIRMED
SUPERSEDED
```

`KnowledgeRecord` and `KnowledgeState` are intentionally distinct concepts. Records preserve epistemic history; state is the current materialized view.

## 7. Verification and consensus

Verification is policy-driven rather than automatically multi-agent.

```text
DETERMINISTIC
     |
     +--> SINGLE_AGENT
     |
     +--> QUORUM
     |
     +--> HUMAN
```

The selected policy depends on risk, required capabilities, available evidence and independence requirements.

Example high-risk policy:

```text
mode = QUORUM
required_capability = security
minimum_votes = 3
independence_required = true
escalate_on_conflict = true
```

A deterministic test result, type check or other reliable machine-verifiable evidence should bypass unnecessary LLM debate.

Persistent disagreement or timeout must terminate in an explicit escalation state rather than an indefinite quorum loop.

## 8. Concurrency model

The Brain must support concurrent workers without silently losing epistemic information.

The target model is:

- append-only epistemic records;
- versioned materialized `KnowledgeState`;
- optimistic concurrency for state transitions;
- explicit conflict handling;
- retryable writes.

Event sourcing and/or implementation-specific storage mechanisms are implementation choices; the architectural invariant is that concurrent observations and evidence cannot silently overwrite each other.

## 9. Failure and recovery

A worker failure is an execution failure, not an agent identity failure.

```text
Worker crashes
     |
     v
Assignment lease expires
     |
     v
Phase 7 recovery/requeue
     |
     v
Another worker retries assignment
```

The Agent Registry therefore does not need to track a permanent `BUSY` state tied to a specific worker process. Any agent availability state introduced later must be lease-aware and recoverable.

## 10. Authority boundary

Brain verification and execution authority are deliberately separate:

```text
Claim
  -> Verification
  -> KnowledgeState = CONFIRMED

Action request
  -> AuthorityEngine
  -> VerifiedAuthorityGrant
  -> Phase 6 execution boundary
```

A Brain result is evidence for a decision; it is not itself an authorization token.

## 11. Scale target

The architecture must support at least 100 persistent agent identities, including multiple instances of the same role, without requiring 100 permanent workers.

Agent selection for verification should be capability- and risk-aware. Quorum selection must avoid unnecessary fan-out and should support escalation when independent reviewers disagree.

## 12. LibreChat integration boundary

LibreChat is an external interaction surface. Integration should occur through a stable adapter/API boundary rather than through direct coupling of EIRA domain models to LibreChat internals.

The adapter may expose operations such as:

- start/continue an interactive agent interaction;
- retrieve agent-facing context;
- submit observations/claims/evidence;
- request human escalation;
- observe assignment/task progress.

The exact transport (API, events/webhooks, etc.) is an implementation decision. The EIRA contracts must remain independent of LibreChat's internal data structures so LibreChat upgrades do not require rewriting the Brain or execution core.

## 13. Implementation sequence

The implementation order is deliberately fixed:

```text
1. Audit existing contracts
2. Map existing code to target architecture
3. Define minimal contracts
4. Write contract tests
5. Implement contracts
6. Implement Brain primitives
7. Integrate Phase 7 assignments/workers
8. Implement LibreChat adapter
9. Add consensus/escalation policies
10. Add production-scale orchestration
```

No new generic `ConversationEngine` is required as a Phase 4 foundation.
