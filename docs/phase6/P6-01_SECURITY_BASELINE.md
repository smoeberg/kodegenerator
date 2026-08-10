# Phase 6 — P6-01 Security Baseline & Threat Model

**Status:** Baseline approved for implementation planning  
**Scope:** Digital Organization Runtime (DOR)  
**Phase:** 6 — Security, Isolation & Supply-Chain Hardening

## 1. Purpose

This document defines the security baseline that all Phase 6 implementation work must preserve and strengthen. It is the security contract for execution isolation, identity, control-plane hardening, supply-chain integrity, and adversarial testing.

The baseline is intentionally aligned with the existing DOR authority model. Phase 6 must harden existing governance boundaries; it must not introduce a parallel authorization model or allow execution code to bypass the runtime authority boundary.

## 2. Security objectives

1. **Least privilege:** every command and execution receives only the capabilities explicitly granted to its principal/actor.
2. **Fail closed:** missing, malformed, expired, ambiguous, or unverifiable security context results in denial.
3. **Organization isolation:** an actor, command, artifact, secret, or execution context must not cross organization boundaries without an explicit authorized path.
4. **Execution isolation:** untrusted agent/module code must not obtain ambient host privileges.
5. **Traceability:** security-relevant decisions and mutations remain attributable to a principal, actor, organization, command, and resource where applicable.
6. **Integrity:** authorization decisions, artifacts, execution evidence, and supply-chain metadata must be tamper-evident.
7. **Reproducibility:** security controls must be deterministic and testable in CI.
8. **Recovery:** a failed or compromised execution must be bounded and recoverable without corrupting trusted control-plane state.

## 3. Trust boundaries

```text
[Human / External Client]
          |
          | authenticated request
          v
[FastAPI Control Plane]
          |
          | principal + organization context
          v
[Runtime Authority / Policy]
          |
          | authorized command
          v
[Task / Agent Orchestration]
          |
          | explicit execution request
          v
[Execution Adapter]
          |
          | isolated boundary
          v
[Sandbox / Container / Process]
          |
          | bounded outputs only
          v
[Evidence + Artifact Pipeline]
          |
          v
[Persistent Audit / State]
```

### Boundary rules

- The control plane is trusted to validate protocol-level input, but is not itself an authorization source.
- `runtime/authority.py` remains the canonical command authorization boundary.
- Downstream agent execution must retain its independent policy/authority decision; a control-plane authorization does not automatically grant agent capabilities.
- The sandbox is considered untrusted from the control-plane perspective.
- Sandbox output is untrusted input until validated by the receiving boundary.
- Secrets must never cross a boundary as unrestricted ambient environment state when a scoped secret reference can be used instead.

## 4. Assets to protect

| Asset | Required protection |
|---|---|
| Organization identity | strict tenant isolation |
| Principal/session credentials | confidentiality, expiry, revocation |
| Actor/role/capability assignments | authorization integrity |
| Policy definitions | integrity and controlled mutation |
| Workflow/task state | authorization + transactional integrity |
| Source repositories | least-privilege access |
| Secrets/API credentials | confidentiality + scoped access |
| Generated artifacts | integrity, provenance, hashability |
| Execution evidence | integrity + attribution |
| Audit events | append-only/tamper-evident semantics |
| Host filesystem/network | sandbox isolation |
| CI/CD credentials | workflow-scoped least privilege |
| Dependency metadata | provenance + reproducibility |

## 5. Threat actors

### T1 — Malicious external client

Can send arbitrary API input and attempt authentication, authorization, object-reference, replay, and protocol attacks.

### T2 — Compromised authenticated principal

Has valid credentials but attempts privilege escalation, cross-organization access, unauthorized mutation, or abuse of legitimate capabilities.

### T3 — Malicious or compromised AI agent

Can generate arbitrary text/code/tool requests and may deliberately attempt to escape policy, access secrets, execute host commands, or manipulate trusted state.

### T4 — Malicious module/plugin/dependency

Executes within an approved workflow but attempts filesystem, network, process, credential, or supply-chain abuse.

### T5 — Compromised infrastructure/deployment identity

Attempts to modify artifacts, runtime configuration, images, dependencies, or audit records.

### T6 — Accidental failure

Malformed inputs, crashes, timeouts, resource exhaustion, stale credentials, partial writes, or corrupted outputs must not become privilege-escalation paths.

## 6. Primary threat scenarios

| ID | Threat | Required mitigation |
|---|---|---|
| TH-01 | Cross-organization object access | organization-scoped authorization on every command/resource path |
| TH-02 | Capability escalation | capabilities derived from authoritative role assignments; execution cannot self-grant |
| TH-03 | Agent escapes execution sandbox | process/container isolation + restricted filesystem/network + resource limits |
| TH-04 | Agent reads host secrets | no ambient secret exposure; scoped secret references |
| TH-05 | Agent reaches internal services | explicit network allowlist / default deny |
| TH-06 | Command injection through execution adapter | structured argv/API; no implicit shell interpolation |
| TH-07 | Replay of privileged command | authenticated request context + command identity + appropriate idempotency/replay controls |
| TH-08 | Stale/revoked credentials remain usable | expiry + revocation checks at security boundary |
| TH-09 | Audit tampering | append-only persistence + integrity fingerprints/evidence |
| TH-10 | Malicious dependency | lock/provenance/fingerprint/SBOM controls |
| TH-11 | Resource exhaustion | CPU, memory, process, disk, output, and wall-clock limits |
| TH-12 | Sandbox output becomes trusted state without validation | schema validation + size/type limits + explicit promotion boundary |
| TH-13 | Web UI embedding/clickjacking | CSP/frame restrictions and secure browser headers |
| TH-14 | CSRF against authenticated browser session | CSRF protection and secure cookie/session policy |
| TH-15 | WebSocket authentication bypass | authentication at connection establishment + authorization per protected operation |

## 7. Security invariants

These are release-blocking invariants for Phase 6:

### INV-01 — No ambient authority

Execution code must not inherit unrestricted host capabilities merely because the parent runtime is trusted.

### INV-02 — No self-escalation

An actor/module cannot modify its own role, capability set, policy, execution limits, or security context to gain additional authority.

### INV-03 — Organization scope is mandatory

Any operation touching organization-owned resources must carry and validate organization scope.

### INV-04 — Authorization precedes mutation/execution

A privileged mutation or execution must not occur before the corresponding authorization decision succeeds.

### INV-05 — Denial is durable/auditable

Security-relevant denials must remain attributable and auditable where the existing audit contract requires an event.

### INV-06 — Sandbox failure is containment

Timeout, crash, OOM, malformed output, or adapter failure must not grant additional authority or corrupt trusted runtime state.

### INV-07 — Secrets are capabilities, not ambient data

Secret access must be explicit, scoped, auditable, and revocable.

### INV-08 — Untrusted output remains untrusted

Agent/module output must be validated before it can become a command, artifact, policy mutation, or other trusted state.

### INV-09 — Security controls fail closed

Unavailable policy state, invalid identity, invalid signature/hash, unknown adapter, or missing security configuration must not silently downgrade protection.

### INV-10 — Supply-chain inputs are verifiable

Production dependencies and execution artifacts must have sufficient provenance to identify exactly what was executed or deployed.

## 8. Existing code mapping

The current repository already contains important Phase 3/4 foundations:

| Existing component | Phase 6 role |
|---|---|
| `domain/authority.py` | canonical capability/role/authorization contracts |
| `runtime/authority.py` | privileged command authorization boundary |
| `domain/authorization_audit.py` | authorization evidence |
| `services/authorization_service.py` | policy/authority evaluation integration |
| `api/auth.py` | authentication hardening target |
| `api/dependencies.py` | request security/context boundary |
| `runtime/policy_engine.py` | policy enforcement hardening target |
| `phase4/` execution components | execution isolation integration point |
| artifact/evidence modules | integrity/provenance enforcement point |
| `.github/workflows/` | CI security gates and supply-chain checks |

Phase 6 implementation must reuse these boundaries where applicable instead of creating competing authorization or identity semantics.

## 9. Required controls by Phase 6 milestone

### P6-02 — Execution sandbox abstraction

- Explicit `ExecutionRequest` and `ExecutionResult` contracts.
- Adapter registry/allowlist.
- No arbitrary shell command interface exposed to agents.
- Security context is immutable from inside the execution boundary.
- Sandbox policy is supplied by the trusted runtime, not by the agent.

### P6-03/P6-04 — Isolation and resource limits

At minimum define and enforce:

- wall-clock timeout;
- CPU quota/time;
- memory limit;
- process/thread limit;
- output size limit;
- writable filesystem scope;
- read-only input scope;
- temporary directory scope;
- network default-deny policy;
- explicit executable/adapter allowlist.

### P6-07/P6-08 — Identity and secrets

- short-lived credentials where practical;
- explicit revocation/expiry semantics;
- rotation support;
- no secrets in logs, artifacts, or audit payloads;
- secret references instead of raw values across execution boundaries;
- fail closed when secret resolution is unavailable.

### P6-09/P6-10 — Control plane

- security response headers;
- CSP appropriate to the dashboard;
- clickjacking protection;
- CSRF protection for browser-authenticated state-changing operations;
- secure cookie/session configuration where applicable;
- WebSocket authentication and authorization;
- strict iframe/embed policy.

### P6-11 — Supply chain

- pinned/locked dependencies;
- dependency provenance;
- SBOM generation;
- artifact digests;
- build provenance suitable for audit;
- CI gate for unexpected dependency drift.

### P6-12/P6-13 — Adversarial and recovery testing

Tests must actively attempt:

- cross-tenant access;
- capability escalation;
- forged/malformed authorization context;
- command replay;
- sandbox filesystem escape;
- sandbox network escape;
- shell/argument injection;
- resource exhaustion;
- secret exfiltration;
- malicious output promotion;
- corrupted artifact/evidence input;
- recovery after timeout/crash/OOM.

## 10. Release gates

Phase 6 cannot be considered complete if any of the following is true:

1. A known release-blocking isolation escape remains open.
2. A privileged operation can execute without the required authorization decision.
3. Cross-organization access is possible through an alternate code path.
4. Agent/module code can self-grant capabilities.
5. Secrets can be obtained through ambient process/container state without explicit authorization.
6. Security controls silently downgrade when configuration or policy state is unavailable.
7. Security-critical tests are skipped in CI.
8. Production dependencies cannot be mapped to a reproducible/provenance-bearing build input.
9. Audit/evidence integrity cannot be verified for security-critical events.
10. An independent security review identifies unresolved release-blocking findings.

## 11. Implementation sequence

1. **P6-01:** establish this baseline and threat model.
2. **P6-02:** introduce execution contracts and adapter boundary without changing runtime behavior unnecessarily.
3. **P6-03/P6-04:** implement the first concrete isolated executor and resource controls.
4. **P6-05/P6-06:** enforce filesystem/network/command restrictions.
5. **P6-07/P6-08:** harden identity, sessions, secrets, and rotation.
6. **P6-09/P6-10:** harden HTTP/browser/WebSocket control-plane surfaces.
7. **P6-11:** add supply-chain evidence and CI gates.
8. **P6-12/P6-13:** add adversarial and recovery suites.
9. **P6-14:** perform audit and close all release-blocking findings.

## 12. Non-goals for P6-01

P6-01 does **not** yet implement:

- a sandbox runtime;
- container orchestration;
- secret storage;
- JWT redesign;
- CSP middleware;
- SBOM generation;
- penetration testing infrastructure.

Those are implementation milestones that consume this baseline.

## 13. Acceptance criteria for P6-01

- [x] Trust boundaries documented.
- [x] Assets documented.
- [x] Threat actors documented.
- [x] Primary threat scenarios documented.
- [x] Security invariants documented.
- [x] Existing security boundaries mapped.
- [x] Phase 6 controls mapped to implementation milestones.
- [x] Release-blocking security gates defined.

**Next implementation target:** P6-02 — Execution Sandbox Abstraction.
