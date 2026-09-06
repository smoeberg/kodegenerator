# Canonical System Specification v1

**Status:** Normative repository-wide system contract  
**Version:** 1.0  
**Introduced against baseline:** `87fa99364699430dd7cd09adc04af2e200ee87b1`

## 1. Purpose and authority

This document is the canonical repository-wide specification for how the implemented Digital Organization Runtime (DOR) composes identity, tenant scope, planning, implementation, verification, traceability and human acceptance into one governed software-delivery flow.

It consolidates existing implemented boundaries. It does not replace lower-level contracts, production code, tests, migrations or CI. When evidence conflicts, the repository-first authority order in `AGENTS.md` applies: fetched `origin/main`, active PR head, production code/tests/migrations/CI, then documentation.

This specification is intentionally explicit about **authority scope**. A result that is authoritative for one contract must never be promoted into execution, merge, release or deployment authority unless a separate governed boundary grants that authority.

## 2. Canonical system shape

```text
Authenticated human / operator
        |
        v
Organization context + membership
        |
        v
Immutable Onboarding Intent
        |
        v
Read-only Project Audit
        |
        v
Human Requirements + non-executing AI-6 Plan
        |
        v
Governed Implementation Proposal
        |
        v
Human Review + Governed Patch Apply
        |
        v
Delivery Verification Candidate
        |
        v
Authoritative Delivery Certificate v1
        |
        v
Immutable Requirement -> Artifact Traceability
        |
        v
Human-authoritative Multi-Spec Artifact Acceptance
        |
        v
Separate release / merge / deploy authority boundary
```

The canonical GUI path is:

1. `dashboard/pages/01_Onboarding.py`
2. `dashboard/pages/02_Project_Audit.py`
3. `dashboard/pages/03_Requirements_And_Plan.py`
4. `dashboard/pages/04_Implementation_Proposal.py`
5. `dashboard/pages/05_Patch_Review_And_Apply.py`
6. `dashboard/pages/06_Delivery_Verification_Handoff.py`
7. `dashboard/pages/07_Delivery_Certificate.py`
8. `dashboard/pages/08_Requirement_Artifact_Traceability.py`
9. `dashboard/pages/09_Multi_Spec_Artifact_Acceptance.py`

The browser is not an authority source. Server-owned runtime state, authenticated identity, organization membership, trusted repository/workspace bindings, fixed tool configuration and persisted records are revalidated at governed boundaries.

## 3. System-wide invariants

The following invariants are normative:

1. **Authenticated identity precedes tenant work.** Tenant-scoped operations derive organization context from an authenticated principal and canonical membership/context checks.
2. **Tenant scope is explicit.** Demo/production pipeline, queue, workflow and worker paths must not fall back to an unscoped global/default tenant state.
3. **Cross-tenant state is denied.** Durable tenant-owned records are accessed under explicit organization scope and PostgreSQL RLS where implemented.
4. **Agent != Assignment != Worker.** Persistent organizational identity is distinct from assigned work and ephemeral compute.
5. **Context != Knowledge.** Task context is not durable epistemic truth.
6. **Knowledge/readiness != execution authority.** Council readiness, confirmed claims, plans, recommendations and trace links do not authorize execution.
7. **Raw authority decisions are not executable.** Governed execution requires the existing verified authority boundary and its bound claims.
8. **Advisory results remain advisory.** Project Audit recommendations are not PASS/FAIL and do not authorize mutation.
9. **Plans remain non-executing proposals.** An AI-6 plan is `authoritative=false` and `executable=false`.
10. **Repository mutation is separately governed.** A patch proposal is not an apply instruction; apply requires a distinct authenticated/authorized command over an exact registered proposal.
11. **Verification provenance is content-addressed.** Candidate/certificate/traceability/acceptance identities bind exact immutable inputs rather than mutable UI state or “latest” records.
12. **PASS is contract-scoped.** Delivery Certificate PASS is authoritative only for Delivery Contract v1.
13. **Traceability is not semantic verification.** `complete` traceability means every exact source requirement has at least one certified artifact link; it does not prove semantic satisfaction.
14. **Acceptance is scope-limited human authority.** Multi-spec artifact acceptance is authoritative only for `multi_spec_artifact_acceptance`; it is not machine semantic verification and grants no release, deploy, merge or execution authority.
15. **Corrections append; they do not rewrite history.** Immutable governed records are superseded or replaced by new content-addressed records where the contract supports correction.
16. **Fail closed on missing trusted provenance.** Missing membership, server-owned apply provenance, trusted toolchain state, workspace state or required persisted bindings must not be converted into a success result.

## 4. Canonical delivery stages

### 4.1 Organization and authentication boundary

**Input:** authenticated principal and configured tenant binding/membership.  
**Authority:** authentication establishes identity; organization context/membership determines whether tenant-scoped commands are allowed.  
**Trusted state:** persistent principal/credential version, JWT keyring, organization membership, runtime context and tenant-scoped persistence.  
**Output:** an authenticated actor operating inside one verified organization context.  
**Does not grant:** blanket access to other organizations or platform-global operations.

Global Swarm operational metrics are a separate platform-operator surface. Being a tenant administrator alone is not platform-operator authority.

### 4.2 Onboarding Intent

**Canonical API:** `POST /api/v1/control-plane/onboarding-intents`  
**Input:** human-declared repository, purpose, rationale and optional target stack/correction reference.  
**Authority:** the human declaration is authoritative only as the declared intent/provenance input; the command still passes tenant context and capability checks.  
**Persistence/trust:** immutable, content-addressed onboarding intent history; corrections create a new intent that may supersede an earlier intent.  
**Output:** exact `intent_id` + `content_fingerprint` bound to organization, repository and declared purpose.  
**Does not grant:** implementation, execution, PASS, release or deployment authority.

`audit_only` intentionally terminates the delivery path after Project Audit.

### 4.3 Project Audit

**Input:** exact onboarding intent and server-owned trusted read-only repository checkout.  
**Authority:** advisory only; `authoritative=false`.  
**Execution boundary:** audit is read-only. The browser cannot choose an arbitrary filesystem path; repository checkout resolution is server-owned and organization-scoped.  
**Output:** content-addressed report/evidence identities, exact audited commit SHA, findings, maturity and recommendation.  
**Does not grant:** PASS/FAIL, mutation, planning authority or execution authority. A non-`audit_only` intent may continue, but `delivery_allowed=true` means only that the declared purpose permits the next governed stage.

### 4.4 Human Requirements and AI-6 Plan

**Input:** exact onboarding + audit provenance plus human-declared `objective`, `acceptance_criteria` and optional `constraints`.  
**Authority:** requirements are the exact human planning declaration. The generated AI-6 plan is explicitly `authoritative=false` and `executable=false`.  
**Content identity:** the planning request fingerprint binds exact requirements to exact onboarding/audit provenance.  
**Output:** immutable proposed plan, plan ID, request fingerprint, steps/rationale/confidence and canonical requirements/provenance.  
**Does not grant:** repository mutation or execution authority.

Audit findings may inform plan steps but remain advisory; the plan must not convert an audit recommendation into authority.

### 4.5 Governed Implementation Proposal

**Canonical API:** `POST /implementation-agent/proposals`  
**Input:** exact current onboarding -> audit -> plan chain, human-visible instruction and explicit bounded repository scope (`allowed_paths`, file budget, changed-line budget).  
**Authority:** the request must pass organization context and implementation capability checks. Governed AI-3/AI-4 authority may authorize the **proposal-generation action**, but the resulting patch proposal itself remains non-authoritative and unapplied.  
**Content identity:** proposal request fingerprint, provider identity, diff SHA-256, touched paths and changed-line count are bound into the proposal identity.  
**Output:** bounded, content-addressed unified diff for human review.  
**Does not grant:** permission to mutate the workspace merely because a proposal exists.

### 4.6 Human Review and Governed Patch Apply

**Canonical API:** `POST /implementation-agent/executions`  
**Input:** exact registered proposal ID and authenticated organization-scoped command. The dashboard revalidates the complete upstream chain and proposal content identity before submitting apply.  
**Authority:** apply is a separate governed capability/authority decision from proposal generation.  
**Server-owned trust:** baseline/workspace, proposal registry, allowed scope, trusted toolchain and fixed verification tools are owned by the runtime rather than supplied as trusted browser claims.  
**Output:** immutable execution/apply record with committed/rolled-back state, committed artifact file manifest, and content-addressed lint/test/build evidence.  
**Mutation:** this is the first stage in the GUI delivery chain that may modify the governed workspace.  
**Does not grant:** release, merge or deployment authority.

### 4.7 Delivery Verification Handoff

**Input:** a successfully committed governed apply with exact artifact and passing lint/test/build evidence.  
**Authority:** none; the candidate is explicitly non-authoritative.  
**Lifecycle:** `pending_authoritative_verification`, `authoritative=false`, `verification_result=null`.  
**Content identity:** `candidate_id` binds organization/repository, onboarding/audit/plan/proposal/apply identities, committed artifact/file states, trusted baseline/toolchain and exact evidence IDs.  
**Output:** `DeliveryVerificationCandidate`.  
**Does not grant:** PASS/FAIL, release, merge, deploy or execution authority.

### 4.8 Authoritative Delivery Certificate v1

**Canonical APIs:**

- `POST /api/v1/control-plane/delivery-certificates`
- `GET /api/v1/control-plane/delivery-certificates/{certificate_id}?organization_id=...`

**Input:** exact delivery candidate. The server reconstructs it and cross-checks server-owned apply provenance, committed artifact/evidence, trusted toolchain/executable fingerprints and current trusted workspace state.  
**Authority:** authoritative **only for Delivery Contract v1**.  
**Result:** immutable `pass` or `fail`. PASS requires every contract check to match; missing server-owned provenance makes certification unavailable rather than fabricated.  
**Persistence:** append-only, tenant-scoped, content-addressed, forced PostgreSQL RLS under migration `028_delivery_certificates`.  
**Does not grant:** execution, merge, release, deployment or production authority.

### 4.9 Requirement -> Artifact Traceability

**Canonical APIs:**

- `POST /api/v1/control-plane/requirement-traceability`
- `GET /api/v1/control-plane/requirement-traceability/{manifest_id}?organization_id=...`

**Input:** exact planning source requirements plus an exact PASS delivery certificate/candidate.  
**Authority:** non-authoritative structural trace contract.  
**Source semantics:** v1 preserves the exact human source text (`objective`, `acceptance_criteria`, optional `constraints`) and does not split/rewrite it into invented requirements.  
**Validation:** artifact links are restricted to the certified candidate file manifest and evidence links to certified candidate evidence IDs; the backend recomputes plan/provenance identity.  
**Status:** `complete` iff every source requirement has at least one artifact link; otherwise `partial`.  
**Persistence:** append-only, tenant-scoped, content-addressed, forced PostgreSQL RLS under migration `029_requirement_traceability`. Multiple immutable manifests may reference one PASS certificate; downstream consumers must reference an exact `manifest_id`, never “latest”.  
**Does not grant:** semantic acceptance, release, merge, deploy or execution authority.

### 4.10 Multi-Spec Artifact Acceptance

**Canonical contract:** `artifact.acceptance.multi_spec.v1`  
**Input:** 2..16 exact COMPLETE traceability manifests, their exact PASS delivery certificates/candidates, at least two distinct plan request fingerprints, same tenant/repository and the same certified artifact file set.  
**Authority:** human-authoritative only within `authority_scope="multi_spec_artifact_acceptance"`; authenticated organization-admin attestation is required.  
**Machine semantics:** `machine_semantic_verification=null`; the backend proves exact bundle/reference integrity, not semantic requirement fulfillment.  
**Persistence:** immutable, tenant-scoped, content-addressed acceptance record under migration `030_artifact_acceptances`.  
**Output:** `accepted` multi-spec artifact acceptance bound to exact manifest/certificate/candidate/spec identities.  
**Does not grant:** `release_authority`, `deploy_authority`, `merge_authority` or `execution_authority`.

### 4.11 Release, merge and deployment

Release, merge and deployment are separate governed boundaries. Delivery PASS, COMPLETE traceability or ACCEPTED multi-spec artifacts may be evidence consumed by a later release/deployment policy, but none of them implicitly performs or authorizes those actions.

Repository-controlled Compose deployment is additionally constrained by the deploy secret-isolation contract: deployment subprocesses do not inherit the control-plane environment, only approved interpolation is allowed, and host-file/build injection surfaces are rejected by policy.

## 5. Tenant and process boundary

The canonical system is multi-tenant by explicit scope, not by caller convention.

- HTTP principals authenticate before tenant-scoped work.
- Runtime commands establish organization context and require canonical membership/capability checks.
- Pipeline registries, workflow lookup/mutation and durable worker activity are selected/bound by verified tenant identity in demo/production; unscoped fallback fails closed.
- Queue and pipeline durable state carry mandatory organization scope.
- PostgreSQL RLS is enabled/forced for canonical tenant-owned persistence where migrations define that boundary.
- Worker principals carry an explicit organization identity before tenant-owned queue/pipeline work.
- Cross-tenant workflow, queue, snapshot and persisted-state access is denied.
- Platform-global operational metrics require the configured platform operator rather than ordinary tenant administration.

Identity principals are authentication records and are not themselves a license to cross organization boundaries.

## 6. Authority interpretation matrix

| Artifact / result | Authoritative? | Exact authority scope | May mutate repository? | Semantic requirement proof? | Release / merge / deploy authority? |
| --- | --- | --- | --- | --- | --- |
| Onboarding Intent | Human declaration only | Declared purpose/provenance | No | No | No |
| Project Audit | No | Advisory report only | No | No | No |
| AI-6 Plan | No | Proposed planning artifact | No | No | No |
| Implementation Proposal | No | Proposed patch artifact | No | No | No |
| Governed Patch Apply record | Governed execution result | Exact patch apply action | Yes | No | No |
| Delivery Verification Candidate | No | Handoff provenance only | No | No | No |
| Delivery Certificate PASS/FAIL | Yes | Delivery Contract v1 only | No | No | No |
| Traceability COMPLETE/PARTIAL | No | Structural reference integrity | No | No | No |
| Multi-Spec Artifact Acceptance | Yes | Human multi-spec artifact acceptance only | No | No (`machine_semantic_verification=null`) | No |
| Release / merge / deploy decision | Separate boundary | Its own explicit contract | Potentially | Contract-dependent | Only if separately granted |

Normative shorthand:

- **Audit recommendation != PASS**
- **Plan proposal != execution authority**
- **Patch proposal != apply authority**
- **Delivery Verification Candidate != Delivery PASS**
- **Delivery Certificate PASS != release/merge/deploy authority**
- **Traceability COMPLETE != semantic requirement satisfaction**
- **Artifact Acceptance ACCEPTED != release/merge/deploy/execution authority**

## 7. Failure and replay semantics

- Commands with idempotency identities may replay only when the semantic request is unchanged; changed input under the same command identity must fail rather than silently mutate history.
- Content-addressed identities are recomputed at trust boundaries; browser/session flags are insufficient evidence.
- Missing or drifting upstream provenance fails the downstream transition.
- Toolchain, executable or workspace drift causes Delivery Contract failure when the contract can be evaluated.
- If required server-owned apply provenance is unavailable, delivery certification is unavailable rather than guessed.
- Immutable corrections create new records; downstream consumers bind exact IDs.

## 8. Canonical implementation references

Repository evidence remains stronger than this summary. Important lower-level contracts include:

- `AGENTS.md` — repository-first operating protocol
- `SECURITY.md` — authentication, tenant and runtime security boundaries
- `docs/PHASE4_ARCHITECTURE.md` — EIRA Brain & Workforce Control Plane architecture
- `docs/ARCHITECTURE_CONTRACT_V1.md` — approved architecture/codegen verification boundary
- `docs/GOVERNED_PATCH_APPLY_GUI.md` — governed proposal/apply GUI boundary
- `docs/DELIVERY_VERIFICATION_HANDOFF.md` — non-authoritative delivery candidate
- `docs/DELIVERY_CERTIFICATE.md` — authoritative Delivery Contract v1
- `docs/REQUIREMENT_ARTIFACT_TRACEABILITY.md` — structural requirement-to-certified-artifact traceability
- `docs/DEPLOYMENT_AND_RELEASE.md` — release/deployment operations
- `docs/DEPLOY_SECRET_ISOLATION.md` — Compose/deploy secret isolation
- `phase4/artifact_acceptance.py` — multi-spec artifact acceptance contract
- `api/main.py` and `api/api_surface.py` — canonical authenticated HTTP surface/inventory

## 9. Explicit non-goals of this specification

This document does not:

- add a new runtime, persistence model, migration or authority model;
- replace existing architecture, security, delivery or traceability contracts;
- claim that requirement semantics are machine-proven;
- grant autonomous multi-agent execution;
- make “latest” records authoritative;
- define a new release/deploy capability;
- certify the demo installation;
- implement the Requirement Steward / multi-agent function deliberation roadmap item.

Those capabilities remain separate work and must preserve the boundaries defined above.
