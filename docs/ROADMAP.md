# Kodegenerator / DOR — Master Architecture & Completion Roadmap

| Metadata | Value |
| --- | --- |
| Document version | 1.0.0 |
| Status | Approved master roadmap |
| Verified baseline | `main` at `e4d88ab`; 366/366 Python tests green |
| Historical checkpoint | Phase 3 complete; 168/168 tests green |
| Target delivery | DOR v1.0 — governed Digital Organization Runtime |

---

## 1. Purpose

This document is the authoritative completion roadmap from the verified Core
Kernel and Phase 4A control-plane contracts to DOR v1.0. It defines delivery
order and acceptance boundaries; it does not claim that unchecked work is
already implemented or production-ready.

DOR v1.0 consists of three first-class product surfaces:

1. the governed Core Runtime;
2. a versioned Core API;
3. the first-party DOR Control Plane GUI.

External modules are optional extensions around those surfaces. They are not a
replacement for the native GUI or a path around Core governance.

## 2. Mandatory architectural principles

These rules apply to every future phase, feature, agent, user interface, and
extension.

1. **GUI as first-party Control Plane.** The GUI is DOR's native Control Plane,
   not an optional module. Every GUI command passes through versioned Core APIs,
   authority evaluation, validated persistence, and immutable audit recording.
2. **Read-only evidence boundaries.** Finalized evidence, artifact
   fingerprints, historical authority decisions, completed verification
   results, and audit events cannot be changed through the GUI or an extension.
   Corrections create new linked records; they never rewrite history.
3. **Fail-closed module isolation.** Modules are optional, independently
   deployable external actors. They use scoped Extension APIs and signed event
   hooks and never access the Core database, persistence adapters, in-process
   runtime state, or execution adapters directly.
4. **Zero self-privilege elevation.** An agent or module may declare requested
   capabilities, but cannot grant, expand, or approve its own roles,
   capabilities, authority, or execution policy.
5. **Independent verification authority.** P3-20 is the sole boundary that
   issues the final `PASS` or `FAIL` verification result. Orchestrators, PM
   agents, Test Agents, Audit Agents, modules, and the GUI cannot overwrite it.
6. **Provenance and fingerprint continuity.** Every contract, context packet,
   task, execution, outcome, evidence item, and delivered artifact maintains a
   reconstructable, fingerprinted provenance chain from intent to delivery.

The canonical write path is:

```text
Control Plane command
  -> versioned Core API
  -> identity, authority, and policy checks
  -> validated state transition
  -> durable persistence
  -> immutable audit event
  -> updated Control Plane state
```

## 3. Current system status

| Area | Status | Verified state |
| --- | --- | --- |
| Phase 1 | Complete | Foundation and Core domain |
| Phase 2 | Complete | Persistence and command runtime |
| Phase 2.1 | Complete | Foundation hardening |
| Phase 3 / P3-18–P3-22 | Complete | Compiler, distribution, verification, execution adapters, and orchestrator |
| Phase 4A / AI-1–AI-7 | Complete reference base | Registry, Context Packet, authority, execution, outcome, planner, and orchestrator contracts |
| Implementation Agent | Partial | Governed bounded proposal contract and AI-1–AI-5 reference flow; operational runtime integration remains |
| Project Audit Agent | Operational | Governed read-only runtime, CLI, baseline provider, and optional OpenAI provider |
| PM Agent | Not started | Required in Phase 4B |
| Test Agent | Not started | Required in Phase 4B |
| First-party Control Plane GUI | Not started | Central DOR v1.0 product surface |
| Durable Phase 4 state | Partial | Several reference registries and result stores remain in process memory |
| Production isolation | Not started | No production agent sandbox or durable worker infrastructure yet |
| End-to-end generation | Not started | No complete intent-to-deliverable pipeline yet |
| Module extension architecture | Specification | Normative design is tracked separately; runtime is not implemented |

The 168-test count remains the historical Phase 3 completion marker. The
current merged `main` baseline records 366/366 Python tests, including focused
integration, CI watcher, and cross-project integrity coverage.

## 4. Phase 4 — Agent ecosystem and governed execution

Phase 4 turns the verified infrastructure runtime into a governed multi-agent
organization engine with an operational first-party Control Plane.

### 4.1 Phase 4A — Governed control-plane foundation (complete)

- [x] **AI-1 Agent Registry:** immutable identity, capability declarations,
  versioning, trust metadata, and provenance.
- [x] **AI-2 Context Packet Engine:** bounded, deterministic, fingerprinted
  context selection with provenance.
- [x] **AI-3 Authority Engine:** exact, fail-closed authority decisions;
  declarations do not grant permission.
- [x] **AI-4 Bounded Execution:** execution occurs only through registered
  adapters under an exact AI-3 `ALLOW` decision.
- [x] **AI-5 Outcome Processing:** immutable, idempotent outcome and state
  transition records.
- [x] **AI-6 Deterministic Planner:** bounded continuation proposals without
  authority or execution powers.
- [x] **AI-7 Orchestrator Contract:** deterministic `CONTINUE`/`STOP` boundary
  that cannot plan, authorize, execute, or rewrite outcomes.
- [x] **Project Audit Runtime:** governed whole-project audit flow and evidence
  production through AI-1–AI-5.

Phase 4A is a verified contract and reference-implementation base. It is not
yet a distributed, durable production runtime.

### 4.2 Phase 4B — Operational specialist agents and Control Plane (current)

#### 4.2.1 Implementation Agent runtime integration

- [ ] Bind the provider adapter to exact Context Packets and authority records.
- [ ] Add a safe patch-apply boundary that cannot broaden the authorized scope.
- [ ] Add allowlisted lint, test, build, and packaging adapters; no free shell or
  agent-selected arbitrary commands.
- [ ] Emit immutable artifacts, evidence, fingerprints, and provenance.
- [ ] Expose one canonical runtime/API command and close the current audit
  finding `implementation-agent-not-runtime-integrated`.

#### 4.2.2 First-party Control Plane GUI and Core API

- [ ] Define versioned REST and WebSocket contracts for commands, queries, live
  execution state, and events.
- [ ] Establish the first-party web application architecture and design system.
- [ ] Deliver **Operational Slice 1 — Create and Launch Project**: capture an
  intent, resolve requirements and contracts, approve the governed plan, and
  start an execution.
- [ ] Deliver project workspace and task-graph views with pause, resume, stop,
  failure, and blocked-state handling.
- [ ] Deliver administration for human users, teams, organizational scopes,
  agents, roles, approved capabilities, and execution policies.
- [ ] Deliver resource administration for providers, models, workers, budgets,
  quotas, artifact storage, and secret references. Raw secrets are never shown
  or stored in frontend state.
- [ ] Deliver approval queues, authority decisions, audit history, and revoke or
  suspension actions through governed command APIs.

The GUI is operational, not generally read-only. Only immutable history and
finalized evidence surfaces remain read-only.

#### 4.2.3 Project Management Agent

- [ ] Convert approved goals and requirements into a deterministic task graph.
- [ ] Define dependencies, assignments, constraints, and deliverables.
- [ ] Preserve bounded decomposition and stable task identities.
- [ ] Prevent the PM Agent from executing, approving, or verifying its own work.

#### 4.2.4 Test Agent

- [ ] Generate requirement-bound test plans and test artifacts.
- [ ] Execute tests only through trusted, allowlisted adapters.
- [ ] Produce coverage and failure evidence with full provenance.
- [ ] Prevent the Test Agent from issuing the final verification result.

### 4.3 Phase 4C — Governed delivery loop

Assemble the specialist agents and existing control-plane boundaries into one
bounded single-run delivery path:

```text
Approved goal
  -> PM task graph
  -> bounded Context Packets
  -> Implementation proposals and execution
  -> Test evidence
  -> Project Audit evidence and recommendation
  -> P3-20 PASS or FAIL
  -> AI-7 CONTINUE or STOP
```

- [ ] Preserve exact identity and provenance across every handoff.
- [ ] Enforce bounded retries, budgets, and terminal stop conditions.
- [ ] Prevent any agent from approving or verifying its own output.
- [ ] Integrate the Project Audit Agent without transferring P3-20 authority.
- [ ] Add GUI execution monitoring, approval workflows, evidence inspection,
  artifact browsing, task graph status, and verification results.
- [ ] Prove one complete governed single-run reference flow.

Branch merging, including any speculative workflow, must be an explicit,
policy-governed operation with verification evidence. It is not an autonomous
GUI shortcut.

### 4.4 Phase 4D — Durable governance, recovery, and idempotency

- [ ] Define persistence ports and durable implementations for projects,
  agents, Context Packets, tasks, executions, outcomes, decisions, evidence,
  artifacts, and orchestration state.
- [ ] Make state transitions transactional, concurrency-safe, and idempotent
  across processes.
- [ ] Enforce authority-decision freshness and replay protection.
- [ ] Resume deterministically after process restart, worker loss, or agent
  interruption without relying on model memory.
- [ ] Maintain append-only event, decision, verification, and audit history.
- [ ] Expose recovery, replay, and history views in the Control Plane.

## 5. Parallel track — Module and extension architecture

The extension architecture is deliberately separate from the Core Runtime and
first-party Control Plane. It does not block the Phase 4B specialist-agent and
GUI work.

- [ ] Merge the normative Module and Extension Architecture Specification.
- [ ] Implement the `module.yaml` schema, canonicalization, and signature
  validation.
- [ ] Implement an immutable module registry and actor binding.
- [ ] Bind requested capabilities to organization-controlled authority policy.
- [ ] Implement a versioned Extension REST/Event API and signed dispatch.
- [ ] Add suspension, revocation, compatibility, replay, SSRF, and isolation
  tests.
- [ ] Add a sandboxed UI Extension Host only after the native Control Plane
  contract is stable.
- [ ] Verify a first external reference module end to end.

The normative design is defined in
[P4 Module and Extension Architecture Specification](phase4/P4_MODULE_EXTENSION_SPECIFICATION.md).

## 6. Phase 5 — End-to-end project generation

Prove a controlled, non-trivial software project before attempting broad
general autonomy.

```text
Intent
  -> Requirements
  -> Compiled Contract
  -> Project Plan and Task Graph
  -> Context Packets
  -> Implementation
  -> Tests
  -> Audit evidence
  -> P3-20 verification
  -> Delivered Project
```

- [ ] Support the complete journey through both the Core API and Control Plane.
- [ ] Maintain deterministic identities and bounded permissions at every step.
- [ ] Require explicit policy-defined human approvals where governance demands
  them; otherwise operate without ad hoc intervention in the runtime pipeline.
- [ ] Produce a complete, inspectable deliverable and provenance bundle.

## 7. Phase 6 — Security, isolation, and supply-chain hardening

- [ ] Isolate agent and module execution at the process or container boundary.
- [ ] Enforce filesystem, network, time, memory, CPU, and output limits.
- [ ] Permit only registered execution adapters and allowlisted commands.
- [ ] Harden identity, sessions, token lifecycle, key rotation, and secret
  references.
- [ ] Apply Control Plane security controls including RBAC, CSRF protection,
  CSP, clickjacking protection, iframe isolation, and secure WebSocket auth.
- [ ] Record dependency provenance, lockfiles, SBOMs, package fingerprints,
  artifact hashes, and signed evidence where required.
- [ ] Run adversarial, penetration, recovery, and authority-bypass tests.
- [ ] Complete independent architecture and security audits with no unresolved
  release-blocking findings.

## 8. Phase 7 — Production runtime infrastructure

- [ ] Deploy durable relational persistence such as PostgreSQL.
- [ ] Deploy S3-compatible object and artifact storage.
- [ ] Deploy resilient queue and event infrastructure with durable workers.
- [ ] Operate versioned API, Project Service, Registry, Context Engine,
  Dispatcher, Execution Service, Verification Gate, Orchestrator, Evidence
  Store, Artifact Store, and Event/Audit Store.
- [ ] Add observability, capacity controls, backups, rollback, disaster
  recovery, and tested restore procedures.
- [ ] Deploy the first-party Control Plane and approved Extension Host under the
  same production governance boundaries.

## 9. Phase 8 — Acceptance and DOR v1.0

The final acceptance test must prove that DOR can accept a complex business
intent and deliver a verified, production-ready system while preserving every
authority, isolation, audit, and provenance boundary.

- [ ] Complete requirements, architecture, planning, tasks, implementation,
  tests, audit, execution, P3-20 verification, and delivery.
- [ ] Complete the same governed project journey through the Control Plane.
- [ ] Recover from a forced interruption without loss or mutation of project or
  governance state.
- [ ] Reproduce the release and verify artifact, dependency, evidence, and
  provenance fingerprints.
- [ ] Complete independent final architecture and security audits.
- [ ] Publish the official DOR v1.0 release.

## 10. Definition of Done

| Domain | DOR v1.0 acceptance criterion |
| --- | --- |
| Contracts | Deterministic, fingerprinted, versioned, and compatibility-checked |
| Agents | Registry, immutable identities, scoped declarations, and externally governed authority |
| Routing | Deterministic and fail-closed |
| Context | Bounded, fingerprinted, reproducible, and provenance-complete |
| Execution | Adapter-bound, isolated, auditable, and resource-limited |
| Evidence | Immutable, provenance-complete, and independently consumable |
| Verification | P3-20 remains the sole final `PASS`/`FAIL` authority |
| Orchestration | Deterministic, bounded, resumable, and unable to bypass authority |
| Control Plane | First-party operational GUI using only governed Core APIs |
| Persistence | Durable state and deterministic recovery after interruption |
| Security | No authority bypass; fail-closed isolation and verified supply chain |
| Artifacts | Fingerprinted, traceable, reproducible, and stored durably |
| End to end | A complex intent-to-deliverable project is independently verified |
| Tests | Full unit, integration, security, recovery, and end-to-end suites are green |
| Audit | Independent architecture and security audits have no release blockers |
| Release | Reproducible DOR v1.0 release with complete provenance |

## 11. Immediate delivery order

1. Merge this roadmap and the Module and Extension Architecture Specification
   as one documentation checkpoint.
2. Implement the Implementation Agent runtime integration.
3. In parallel, define the Core API and Control Plane architecture, then deliver
   the operational **Create and Launch Project** slice.
4. Implement PM and Test Agents.
5. Assemble and verify the Phase 4C governed delivery loop.
6. Complete durable governance and recovery before production acceptance.
7. Continue through end-to-end generation, security hardening, production
   infrastructure, and DOR v1.0 acceptance.
