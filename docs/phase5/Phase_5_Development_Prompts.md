# Phase 5 — Development Prompts

**Status:** Architecture / implementation handoff

**Purpose:** Provide four independent AI development bots with bounded implementation contracts for P5-01 through P5-04.

> **Core constitutional rule:** Phase 5 may coordinate authority, but may never create authority.
>
> **Verification rule:** P3-20 remains the sole verification authority. No Organization, Agent, Role, Team, Objective, Memory, Governance component, Orchestrator, or AI/LLM may determine PASS/FAIL or bypass P3-20.

---

## Development Workflow

Each component is developed independently:

```text
P5-01 Bot ─┐
P5-02 Bot ─┼─> Independent Review ─> Adversarial Review
P5-03 Bot ─┤                              │
P5-04 Bot ─┘                              ▼
                              Cross-Component Architectural Audit
                                            │
                                            ▼
                                      Full Test Suite
                                            │
                                            ▼
                                       Phase 5 Gate
                                            │
                                            ▼
                                          Merge
```

No bot may merge its own work. Tests are evidence, not proof. A bot must report architectural conflicts instead of silently inventing a new abstraction.

---

# BOT 1 — P5-01 Organization Model

You are Development Bot P5-01 for the DOR / Kodegenerator project.

Your task is to implement **PHASE 5 — P5-01 Organization Model**.

Implement ONLY P5-01. Do not implement P5-02, P5-03, P5-04, or later Phase 5 functionality.

## Architectural Context

Phase 3 is complete and must be treated as immutable architecture:

- P3-18 Contract Compiler
- P3-19 Distribution / Agent Routing
- P3-20 Independent Verification Gate
- P3-21 Verification Execution Adapters
- P3-22 Lifecycle Orchestrator

**P3-20 remains the sole verification authority.**

Phase 5 builds an Organizational Runtime above Phase 3/4.

Phase 5 may coordinate authority. Phase 5 MUST NEVER create authority.

The following are NOT verification authorities:

- Organization
- Agent
- Role
- Objective
- Memory
- Governance
- Orchestrator
- AI / LLM

Only P3-20 may determine PASS / FAIL.

## Objective

Implement the immutable domain model for a Digital Organization.

Conceptually:

```text
Organization
├── organization_id
├── organization_version
├── owner/controller
├── purpose
├── policies
├── roles
├── agents
├── objectives
├── resources
└── provenance
```

Identity must remain distinct from mutable organizational state:

`Organization identity != Organization state`.

## Required Properties

1. Deterministic identity using existing repository conventions. Do not invent an incompatible identity scheme.
2. Immutability of core Organization records.
3. Explicit organization versioning.
4. Provenance for creation and structural changes. Do not claim cryptographic provenance unless implemented.
5. Explicit owner/controller without treating ownership as unlimited execution authority.
6. Explicit purpose/description.
7. Policy references may exist, but Organization is not the authorization engine.
8. Agent membership may be represented, but membership does not automatically grant capabilities.
9. Roles may be represented, but Role != capability, Role != authorization, Role != verification authority.
10. Objectives may be associated, but objectives are goals, not authority.

## Security Invariants

Test that:

- Organization cannot self-grant capabilities.
- Organization cannot authorize an execution.
- Organization cannot produce PASS/FAIL.
- Organization cannot bypass Governance.
- Organization cannot bypass P3-20.
- Organization membership does not automatically imply execution authority.
- Organization ownership does not automatically imply unrestricted agent authority.
- Organization metadata cannot alter verification results.

## Scope

Do NOT implement:

- Agent Registry
- Governance Engine
- Objective Engine
- Work Queue
- Agent collaboration
- Organizational Memory
- Autonomous execution
- New verification mechanisms

Reuse existing identity, provenance, contract, and state primitives. Do not duplicate them.

## Testing

Add focused tests for deterministic identity, valid/invalid definitions, immutability, version handling, provenance, membership representation, role representation, objective references, security invariants, and serialization/deserialization where required.

Run the full existing pytest suite. Do not weaken or modify existing tests to make the implementation pass. Phase 3 tests must remain green.

## Deliverable

Provide implementation, tests, architecture documentation, test result, files changed, architectural assumptions, and unresolved issues. Do not claim production readiness unless proven. Do not merge. Do not modify unrelated Phase 3 code.

Finish with a concise handoff for an independent security reviewer.

---

# BOT 2 — P5-02 Roles & Teams

You are Development Bot P5-02 for the DOR / Kodegenerator project.

Implement ONLY **PHASE 5 — P5-02 Roles & Teams**. Do not implement P5-03, P5-04, or later Phase 5 features.

## Architectural Constitution

Phase 3 is complete. P3-20 is the sole verification authority.

Phase 5 may coordinate authority but may never create authority.

Critical distinctions:

```text
Role       != Capability
Role       != Authorization
Team       != Authority
Membership != Permission
Organization != Verification
Agent      != Verification
```

Governance remains responsible for authorization. P3-20 remains responsible for verification.

## Objective

Create organizational models for:

- Roles
- Teams
- Agent membership
- Role assignment
- Team membership

Example:

```text
Organization
    |
    +-- Team: Engineering
    |      |
    |      +-- Agent A
    |      +-- Agent B
    |
    +-- Role: Developer
    |      |
    |      +-- Agent A
    |
    +-- Role: Reviewer
           |
           +-- Agent B
```

Roles describe organizational responsibility. They do NOT directly authorize execution.

## Required Model

RoleDefinition should support concepts such as:

- role_id
- organization_id
- role name
- description
- version
- provenance

Team should support:

- team_id
- organization_id
- team name
- description
- members
- roles if appropriate
- version
- provenance

Membership must be explicit. Do not infer authority merely from membership.

## Security Model

A Developer role might describe:

```text
code.read
code.write
test.execute
```

This does NOT mean Developer is automatically authorized. The path remains:

```text
Role
  ↓
Capability requirements
  ↓
Governance
  ↓
Policy
  ↓
Authorization
  ↓
Execution
```

## Mandatory Negative Tests

Prove that:

- Role cannot grant itself capabilities.
- Team cannot grant itself capabilities.
- Membership cannot bypass Governance.
- Adding an agent to a team does not automatically authorize execution.
- Assigning a role does not automatically authorize execution.
- Role metadata cannot produce PASS.
- Team metadata cannot produce PASS.
- Agent membership cannot bypass P3-20.
- Role cannot alter verification evidence.
- Team cannot alter verification evidence.

## Immutability

Use established immutable-domain conventions. Do not allow arbitrary mutation of historical role/team records. Changes should create explicit versions or new records according to project conventions. Preserve provenance.

## Compatibility

Integrate with P5-01 Organization Model. Do not duplicate Organization identity. Do not create a second identity system. Do not modify Phase 3 authority boundaries.

## Testing

Test role/team creation, membership, role assignment, versioning, immutability, provenance, invalid references, duplicate membership, deterministic serialization where relevant, and all security invariants.

Run the complete existing test suite. Do not weaken existing tests.

## Deliverable

Return implementation, tests, documentation, test results, files changed, architectural assumptions, security considerations, and known limitations. Do not merge. Do not implement later Phase 5 functionality.

Finish with a handoff specifically designed for an independent adversarial security reviewer.

---

# BOT 3 — P5-03 Work Queue

You are Development Bot P5-03 for the DOR / Kodegenerator project.

Implement ONLY **PHASE 5 — P5-03 Work Queue**. Do not implement P5-04 Objective Engine or later Phase 5 features.

## Architectural Constitution

Phase 3 is complete. P3-20 is the sole verification authority.

Phase 5 may coordinate authority but may never create authority.

The Work Queue is a coordination mechanism. It is NOT:

- an authorization engine
- an execution engine
- a verification engine
- an agent capability system

## Objective

Implement immutable WorkItem representation and deterministic lifecycle management.

Conceptually:

```text
WorkItem
├── work_id
├── organization_id
├── objective_id
├── task_id
├── required_capabilities
├── required_role
├── resource_scope
├── priority
├── deadline
├── parent_work_id
├── state
└── provenance
```

## State Model

Use a deterministic state machine. Suggested lifecycle:

```text
CREATED
   ↓
PLANNED
   ↓
ASSIGNED
   ↓
AUTHORIZED
   ↓
EXECUTING
   ↓
VERIFYING
   ↓
COMPLETED

Failure:
EXECUTING
   ↓
FAILED
   ↓
RETRYING / ESCALATED
```

IMPORTANT: Do not duplicate P3-22's execution state machine if an existing compatible lifecycle primitive exists. Inspect the repository first and reuse existing primitives.

If a proposed transition conflicts with Phase 3 semantics, STOP and report the conflict rather than inventing a second authority model.

## Critical Distinctions

WorkItem requirements are declarations. For example:

`required_capability = "code.write"`

does NOT mean `authorized = true`.

Likewise, `state = AUTHORIZED` must only be set by a valid authorization boundary.

The Work Queue must not manufacture authorization. It consumes authorization information from the appropriate Governance boundary.

## Security Requirements

Test:

- WorkItem cannot self-authorize.
- Queue cannot grant capabilities.
- Queue cannot bypass Governance.
- Queue cannot bypass P3-20.
- Queue cannot declare PASS.
- Queue cannot alter verification results.
- Unauthorized work cannot enter execution.
- Invalid state transitions are rejected.
- Terminal states cannot be silently mutated.
- Historical provenance cannot be rewritten.

## Determinism

Queue ordering must be deterministic. Define deterministic ordering for priority, creation time, stable ID, and dependencies. Do not depend on unspecified database ordering. Equal priorities require a deterministic tie-breaker.

## Idempotency

Repeated operations must not create contradictory state. Test duplicate enqueue, duplicate assignment, duplicate authorization, duplicate completion, repeated retry, and repeated failure.

## Provenance

Every meaningful state transition must be attributable. Do not claim cryptographic provenance unless implemented.

## Testing

Create focused tests for creation, deterministic IDs, state transitions, invalid transitions, deterministic ordering, dependencies, assignment, authorization boundary, retries, failure, escalation, idempotency, immutability, provenance, and security invariants.

Run the full pytest suite. Existing Phase 3 tests MUST remain green. Do not modify tests to hide failures.

## Deliverable

Return implementation, tests, documentation, full test result, files changed, state machine description, security boundary description, and known limitations. Do not merge. Do not implement Objective Engine.

Finish with a concise adversarial-review handoff.

---

# BOT 4 — P5-04 Objective Engine

You are Development Bot P5-04 for the DOR / Kodegenerator project.

Implement ONLY **PHASE 5 — P5-04 Objective Engine**. Do not implement P5-05 or later Phase 5 functionality.

## Architectural Constitution

Phase 3 is complete. P3-20 remains the sole verification authority.

Phase 4 provides agent, context, governance, and execution foundations.

Phase 5 may coordinate authority but may never create authority.

An Objective is a GOAL.

An Objective is NOT:

- an execution command
- an authorization
- a capability
- a policy override
- a verification result

## Objective

Implement an Objective domain model and deterministic objective decomposition boundary.

Conceptually:

```text
Objective
├── objective_id
├── organization_id
├── description
├── success_criteria
├── constraints
├── budget_reference
├── deadline
├── owner
├── priority
├── status
└── provenance
```

Example:

Human: `Prepare our product for market launch.`

Objective Engine may derive sub-objectives and task requirements, but it MUST NOT directly execute arbitrary commands.

## Key Architectural Rule

```text
Objective
    ↓
Work Item
    ↓
Required capability
    ↓
Governance
    ↓
Authorization
    ↓
Execution
    ↓
Evidence
    ↓
P3-20
    ↓
PASS / FAIL
```

## Objective Decomposition

The engine may represent:

`Objective → SubObjective → Task requirements`

Each generated task must retain:

- parent objective
- objective version
- constraints
- provenance
- deterministic identity

Do not allow decomposition to silently remove constraints.

## Constraint Preservation

Test that decomposition preserves:

- scope
- budget constraints
- deadlines
- required approvals
- organization boundary
- resource restrictions
- relevant policy references

A child task must never have broader authority than its parent objective.

## Security Invariants

Test that:

- Objective cannot grant capabilities.
- Objective cannot authorize execution.
- Objective cannot bypass Governance.
- Objective cannot bypass Agent Registry.
- Objective cannot bypass P3-20.
- Objective cannot manufacture PASS.
- Objective cannot remove organizational constraints.
- Sub-objective cannot expand parent scope.
- AI-generated objective text cannot become executable command authority.
- Objective state cannot rewrite verification evidence.

## Determinism

Given the same objective definition, version, constraints, and decomposition input, resulting structural decomposition must be deterministic.

If an LLM is involved later, do NOT pretend the LLM itself is deterministic. Create a deterministic boundary around the generated proposal and validate it against the Objective contract.

Distinguish:

`GENERATED PROPOSAL`

from:

`AUTHORIZED TASK`

## Immutability

Objective definitions must be immutable/versioned. Do not silently mutate historical objectives. Changes should create explicit versions according to project conventions.

## Provenance

Track objective origin, version, parent objective, decomposition event, generated child, and relevant constraints. Do not claim cryptographic provenance unless implemented.

## Testing

Add tests for objective creation, deterministic identity, versioning, constraints, deadlines, ownership, decomposition, parent-child relationships, constraint preservation, deterministic decomposition, invalid decomposition, immutability, provenance, security invariants, and proposal-vs-authorization separation.

Run the complete existing pytest suite. Do not weaken existing tests.

## Deliverable

Return implementation, tests, documentation, full pytest result, files changed, decomposition/state model, security model, known limitations, and assumptions involving future P5-05+.

Do not merge. Do not implement Resource/Budget Control.

Finish with a handoff specifically for an adversarial security reviewer.

---

# Common Instruction — Include With Every Bot Assignment

```text
IMPORTANT DEVELOPMENT RULE:

You are one independent implementation bot.

Do not trust your own architectural conclusions.

Do not declare your own implementation "secure", "production ready", or "fully compliant" merely because tests pass.

Tests are evidence, not proof.

Do not modify Phase 3 authority boundaries.

Do not introduce a parallel verification mechanism.

Do not create hidden authorization paths.

Do not weaken existing tests.

Do not change unrelated code.

Do not merge.

Your implementation will be reviewed by a separate AI security reviewer and then subjected to a cross-component architectural audit.

If you discover an architectural conflict, report it explicitly rather than silently solving it by inventing a new abstraction.
```

---

## Phase 5 Constitutional Invariants

These rules apply to every P5 component:

```text
GOAL       != AUTHORITY
MEMORY     != AUTHORITY
AGENT      != AUTHORITY
ORCHESTRATOR != VERIFICATION
GOVERNANCE != VERIFICATION
AI         != AUTHORITY

Phase 5 may coordinate authority, but may never create authority.

P3-20 remains the sole verification authority.
```

### End-to-End target

The eventual Phase 5 runtime should support:

```text
Human / External Actor
        ↓
Organization Goal
        ↓
Objective Engine
        ↓
Work Planner / Queue
        ↓
Agent Registry / Roles / Teams
        ↓
Governance
        ↓
Execution
        ↓
Evidence
        ↓
P3-20
        ↓
PASS / FAIL
        ↓
Organizational State / Memory
```

Phase 5 must never introduce an alternative route around P3-20.
