# P4-00C — Verified Authority & Governed Dispatch Test Contract

**Status:** normative test contract
**Phase:** 4
**Gate:** P4-00C
**Precondition:** P4-00A characterization findings F-001/F-002 preserved unchanged

## 1. Purpose

P4-00C proves that execution authority can only be established through an independently verifiable governed dispatch. A raw `AuthorizationDecision`, agent claim, context value, or direct runtime invocation is never itself execution authority.

Normative invariant:

```text
Raw AuthorizationDecision != Authority
Raw Execution Request != Authorized Dispatch
Context != Authority
Agent claim != Authority

Authoritative AI-3 grant
  + exact binding
  + valid lifetime
  + valid replay state
  -> VerifiedAuthorityGrant
  -> GovernedDispatch
  -> Execution
```

## 2. Preservation rule

The existing P4-00A characterization tests are historical evidence and MUST NOT be weakened, deleted, or rewritten to hide the original reachability findings. P4-00C tests are additional normative regression tests.

## 3. Dispatch boundary

The test suite MUST prove:

- direct `ExecutionEngine` invocation without a verified governed dispatch is rejected;
- direct trusted-tool/adapter execution without a verified governed dispatch is rejected;
- execution-mediated repository mutation without a verified governed dispatch is rejected;
- callers cannot manufacture a dispatch merely by constructing a structurally similar object.

A rejected request MUST cause no execution, repository mutation, trusted-tool invocation, evidence receipt, or verification PASS.

## 4. AI-3 provenance

The suite MUST prove:

- a hand-constructed `AuthorizationDecision(allowed=True, ...)` is rejected as execution authority;
- an unknown decision identifier is rejected;
- an untrusted/non-authoritative issuer is rejected;
- mutation of an issued decision is rejected;
- authority cannot be laundered by copying/reconstructing an equivalent-looking decision object.

## 5. Exact binding

A valid authority grant MUST be bound to the exact:

- organization;
- actor;
- agent;
- capability;
- action;
- resource;
- request fingerprint;
- context fingerprint;
- policy version.

Changing any of these MUST cause dispatch rejection.

## 6. Fingerprints

The suite MUST prove:

- canonical equivalent requests produce the same deterministic request fingerprint;
- semantic request changes produce a different fingerprint;
- context changes produce a different context fingerprint;
- a request fingerprint mismatch is rejected;
- a context fingerprint mismatch is rejected;
- a policy-version mismatch is rejected.

## 7. Temporal validity

The suite MUST prove:

- expired grants are rejected;
- not-yet-valid grants are rejected;
- fresh, otherwise valid grants are accepted.

## 8. Replay

The suite MUST prove:

- the same execution identity cannot be executed twice;
- nonce/replay identity cannot be reused across actors;
- nonce/replay identity cannot be reused across organizations;
- nonce/replay identity cannot be reused across agents;
- legitimate retry creates a new attempt without rewriting historical execution state.

## 9. Context isolation

The suite MUST prove that untrusted context cannot:

- grant a capability;
- expand resource scope;
- establish approval/authority;
- replace or mutate the authoritative AI-3 decision.

Provider/LLM output is proposal data only and MUST be re-authorized as a typed request.

## 10. Revocation and authority freshness

P4-00C MUST provide the seam needed to demonstrate rejection after:

- explicit grant revocation;
- agent deactivation after approval;
- authority generation/policy state changing after approval.

Full revocation hardening remains part of P4-01, but P4-00C MUST NOT establish an execution path that inherently assumes stale authority remains valid.

## 11. Positive proof

At least one non-mocked runtime test MUST prove the complete governed path:

```text
Active agent
-> declared capability
-> organization-controlled authority
-> AI-3 decision
-> fresh authority grant
-> bounded Context Packet
-> request fingerprint
-> P3-19 dispatch
-> AI-4 execution
-> governed evidence
-> P3-20
-> PASS
```

The test MUST exercise the actual runtime seams. Security-critical authority, dispatch, identity, capability, provenance, or verification seams MUST NOT be mocked.

## 12. Negative-test rule

Security tests MUST verify not only rejection but the absence of side effects:

- no execution;
- no repository mutation;
- no trusted-tool invocation;
- no authoritative evidence receipt;
- no final PASS.

Denied attempts MAY produce audit events.

## 13. Required test inventory

### Dispatch
- `test_direct_execution_without_dispatch_is_rejected`
- `test_direct_trusted_tool_execution_without_dispatch_is_rejected`
- `test_direct_repository_mutation_without_dispatch_is_rejected`
- `test_raw_execution_request_cannot_become_dispatch`

### Provenance
- `test_forged_ai3_decision_is_rejected`
- `test_unknown_decision_id_is_rejected`
- `test_non_authoritative_issuer_is_rejected`
- `test_modified_ai3_decision_is_rejected`
- `test_authority_laundering_is_rejected`

### Binding
- `test_wrong_organization_is_rejected`
- `test_wrong_actor_is_rejected`
- `test_wrong_agent_is_rejected`
- `test_wrong_capability_is_rejected`
- `test_wrong_action_is_rejected`
- `test_wrong_resource_is_rejected`

### Fingerprints
- `test_request_fingerprint_mismatch_is_rejected`
- `test_context_fingerprint_mismatch_is_rejected`
- `test_policy_version_mismatch_is_rejected`
- `test_request_fingerprint_is_deterministic`

### Temporal
- `test_expired_grant_is_rejected`
- `test_not_yet_valid_grant_is_rejected`
- `test_fresh_grant_is_accepted`

### Replay
- `test_same_dispatch_cannot_execute_twice`
- `test_nonce_cannot_cross_actor`
- `test_nonce_cannot_cross_organization`
- `test_nonce_cannot_cross_agent`
- `test_retry_creates_new_attempt_without_rewriting_history`

### Context
- `test_context_cannot_grant_capability`
- `test_context_cannot_expand_resource_scope`
- `test_context_cannot_become_authority`

### Freshness/revocation
- `test_revoked_grant_is_rejected`
- `test_deactivated_agent_after_approval_is_rejected`
- `test_stale_authority_generation_is_rejected`

### Positive proof
- `test_valid_ai3_to_ai4_governed_dispatch_succeeds`

## 14. RED requirement

Before production remediation is implemented, the applicable P4-00C tests MUST be present and failing for the documented reasons. Production changes MUST NOT be used to make the initial RED state disappear without a corresponding test proving the original invariant.

## 15. Exit criteria

P4-00C is GREEN only when:

1. all applicable P4-00A characterization tests remain preserved;
2. all P4-00C normative tests pass;
3. no security test is skipped or marked expected-failure;
4. the positive proof exercises actual runtime seams;
5. the negative tests demonstrate absence of execution side effects;
6. direct runtime invocation and forged AI-3 authority are structurally rejected.

P4-00C GREEN is a prerequisite for P4-00D adversarial falsification and final P4-00 gate review.
