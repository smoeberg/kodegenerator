# DOR Phase 3 — Authority & Execution Contract v0.1

**Status:** Contract baseline

**Branch:** `phase3/authority-execution-contract`

**Predecessor:** `foundation/v0.1-persistence`

**Scope:** Authority, authorization, command execution, and audit semantics.

---

## 1. Purpose

Phase 3 establishes the runtime authority boundary of DOR.

The objective is to make every state-changing operation answer four questions deterministically:

1. Who is calling?
2. Which Actor is acting?
3. Which organization context applies?
4. Does that Actor have the required capability for the requested operation on the target resource?

Authorization is a runtime invariant, not an optional application feature.

---

## 2. Architectural Boundary

The canonical execution path is:

```text
Principal
   ↓
OrganizationContext
   ↓
Actor
   ↓
RoleAssignment(s)
   ↓
RoleDefinition
   ↓
Capability
   ↓
AuthorizationDecision
   ↓
Command
   ↓
Aggregate
   ↓
Domain Event(s)
   ↓
Unit of Work
   ↓
Persistence
```

No state-changing application operation may bypass the authorization boundary.

---

## 3. Principal

`Principal` represents the authenticated caller identity entering the runtime.

Minimum contract:

```text
Principal
- id: string
- type: string
- metadata: mapping
```

A Principal is not itself an organizational authority grant.

The runtime must bind the Principal to an Actor explicitly before executing organization-scoped work.

A Principal/Actor mismatch MUST result in denial.

---

## 4. Actor

`Actor` represents the organizational entity that performs an operation.

Supported actor types remain:

- HUMAN
- DIGITAL_EMPLOYEE
- SERVICE
- EXTERNAL

Minimum persisted identity:

```text
Actor
- id
- organization_id
- type
- identity
- status
```

An Actor MUST belong to the organization in the active runtime context.

Inactive or suspended Actors MUST NOT execute state-changing commands.

---

## 5. Roles

A RoleDefinition describes authority; it does not identify the Actor holding it.

The Phase 3 model SHALL separate:

```text
Actor
  ↓
RoleAssignment
  ↓
RoleDefinition
```

Role assignment is organization-scoped.

The initial contract requires enough information to determine:

```text
actor_id
organization_id
role_definition_id
status
created_at
```

The implementation must not use a single embedded `actor.role` field as the canonical authorization source.

---

## 6. Capabilities

A Capability is an atomic permission that can be evaluated by the runtime.

Canonical naming is dot-separated and action-oriented.

Examples:

```text
workflow.read
workflow.create
workflow.transition
workflow.approve
workflow.release
artifact.read
artifact.create
artifact.approve
```

Capability identifiers MUST be stable strings.

Capabilities are granted through RoleDefinitions and MUST NOT be inferred from UI behavior or command names alone.

---

## 7. Authorization Decision

Authorization SHALL have one explicit runtime boundary.

Conceptually:

```text
authorize(
    principal,
    actor,
    organization,
    capability,
    resource
) -> AuthorizationDecision
```

The decision is deterministic and contains at minimum:

```text
AuthorizationDecision
- allowed: bool
- reason: string
```

An implementation MAY include additional audit/context fields.

A denial MUST be explainable without exposing secrets or unrelated tenant data.

---

## 8. Mandatory Denials

The runtime MUST deny execution when any of these conditions applies:

1. Runtime is not ready.
2. Principal cannot be bound to the requested Actor.
3. Actor does not belong to the organization context.
4. Actor is inactive or suspended.
5. Required capability is not granted.
6. Target resource belongs to another organization.
7. Command organization does not match runtime context.
8. Command data conflicts with an existing command receipt.

Authorization failures MUST NOT be converted into successful no-op execution.

---

## 9. Command Boundary

Commands represent requested state changes.

A command MUST:

- have a stable command ID;
- identify its organization context;
- identify its target aggregate where applicable;
- carry only the data needed to perform the operation;
- be authorized before mutation;
- execute atomically with resulting domain events.

The existing command idempotency contract remains authoritative.

A repeated command ID with identical command data SHALL return the existing execution result where supported.

A repeated command ID with conflicting actor, organization, command type, or payload MUST be rejected as a conflict.

---

## 10. Aggregate Boundary

Domain aggregates remain responsible for domain invariants.

Authorization is not an aggregate responsibility.

The separation is:

```text
Authorization
  → Is this Actor allowed to request this operation?

Aggregate
  → Is this operation valid for the current domain state?
```

Both checks are required.

---

## 11. Events

Successful state-changing commands MUST produce domain events where the domain operation changes observable state.

Events remain durable and organization-scoped.

The existing event fields remain part of the foundation contract:

- event ID
- event type
- aggregate ID/type
- organization ID
- actor ID
- timestamp
- correlation ID
- causation ID
- metadata
- schema version
- aggregate sequence

Phase 3 SHALL extend event semantics rather than introduce a parallel audit persistence mechanism.

---

## 12. Authorization Audit

Authorization decisions that materially affect state-changing execution SHALL be auditable.

At minimum, an audit record/event must be able to establish:

```text
who      → actor/principal
where    → organization
what     → capability / command
resource → target aggregate/resource where applicable
result   → allow / deny
when     → timestamp
why      → decision reason/code
```

Sensitive credentials, secrets, tokens, or private payload data MUST NOT be copied into audit records.

---

## 13. Transaction Boundary

The existing Unit of Work remains the transaction boundary.

For a successful command:

```text
authorize
  ↓
load aggregate
  ↓
validate domain operation
  ↓
apply/persist aggregate state
  ↓
persist event(s)
  ↓
persist command receipt
  ↓
commit
```

Failure MUST roll back the complete state-changing transaction.

No partial aggregate/event/command state is acceptable.

---

## 14. Organization Isolation

Organization isolation is mandatory at every persistence and authorization boundary.

A caller from organization A MUST NOT:

- read organization B resources through an organization-scoped API;
- mutate organization B resources;
- use organization B role assignments;
- use organization B capabilities to authorize an operation in A;
- infer protected resource existence through authorization behavior.

Cross-organization access MUST fail closed.

---

## 15. Legacy Boundary

Existing domain helpers such as `Actor.can_perform()` may remain temporarily for compatibility, but they are not the canonical Phase 3 authorization mechanism.

The canonical mechanism is:

```text
Actor
→ RoleAssignment
→ RoleDefinition
→ Capability
→ AuthorizationDecision
```

New Phase 3 code MUST NOT introduce additional scattered `can_*` authorization checks.

---

## 16. Test Contract

Phase 3 is not complete until all existing foundation tests remain green and the following gates exist:

```text
P3-01  Principal → Actor binding
P3-02  Actor → Organization isolation
P3-03  Role assignment
P3-04  Capability grant
P3-05  Capability denial
P3-06  Authorization decision
P3-07  Unauthorized command rejected
P3-08  Authorized command succeeds
P3-09  Authorization audit
P3-10  Cross-organization authorization denied
P3-11  Existing foundation regression suite remains green
```

Required invariant:

```text
Foundation tests + Phase 3 tests = 0 regressions
```

---

## 17. Non-Goals

Phase 3 does NOT introduce:

- AI orchestration;
- LLM execution;
- UI/dashboard work;
- GitHub automation;
- external workflow providers;
- distributed authorization;
- multi-node consensus;
- blockchain or decentralized identity;
- OAuth/OIDC implementation unless required by a later explicit contract.

Those concerns remain outside this foundation boundary.

---

## 18. Implementation Order

Implementation MUST follow this order:

1. Formalize RoleDefinition contract.
2. Add RoleAssignment model and persistence boundary.
3. Formalize Capability contract.
4. Add role-to-capability resolution.
5. Implement AuthorizationDecision and central authorization service.
6. Integrate authorization with command execution.
7. Add authorization audit semantics.
8. Add Phase 3 tests.
9. Run complete regression suite.
10. Perform architecture audit before merge.

No later item should be implemented by bypassing an earlier contract.

---

## 19. Completion Criteria

Phase 3 Authority & Execution Foundation is complete only when:

- authority is explicit and organization-scoped;
- authorization has one canonical runtime boundary;
- commands cannot mutate state without authorization;
- domain invariants remain inside aggregates;
- command, aggregate, event, and persistence operations remain atomic;
- authorization outcomes are auditable;
- cross-organization access fails closed;
- all Phase 3 gates pass;
- all existing foundation tests pass;
- no legacy authorization path is used by new Phase 3 code.

**Contract status: READY FOR IMPLEMENTATION.**
