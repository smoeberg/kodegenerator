# P4-00D Independent Adversarial Re-Verification

**Status:** COMPLETED — NO P0/P1 AUTHORITY BYPASS OBSERVED  
**Does not close [#43](https://github.com/smoeberg/kodegenerator/issues/43)** — review-of-reviewer still required.

| Field | Value |
|-------|--------|
| Issue | [#43 — P4-00 Cross-Agent Authority Verification](https://github.com/smoeberg/kodegenerator/issues/43) |
| Reviewed head | `main` @ `8fd15de0c3fab7d3480cc693e5d50f4b6f59bc99` |
| Merged remediation | PR #73 (`1cd65e9` — authenticate and expire authority grants) |
| Prior implementer doc | `docs/phase4/P4_00D_SECURITY_REVIEW.md` (not independent) |
| Review date (UTC) | 2026-08-18 |
| Suite | `tests/phase4/p4_00d/test_authority_gate_adversarial.py` |
| Production seams | `phase4.authority.grants`, `phase4.execution.engine` |

## Independence statement

This report is **not** the implementer security write-up in
`P4_00D_SECURITY_REVIEW.md`. It is a separate adversarial re-verification of
the merged boundary on current `main`.

The reviewer did not author PR #72/#73 implementation code. This document must
still undergo **review-of-reviewer** before #43 may close.

## Method

1. Read `VerifiedAuthorityGrant` / `ExecutionEngine` on the reviewed head.
2. Execute the full focused adversarial suite and additional independent probes.
3. For every rejection path, require:
   - `ExecutionStatus.REJECTED` (or grant issuance `ValueError` where applicable),
   - `output == ()`,
   - adapter `calls == 0`.
4. Mutate credentials with both `dataclasses.replace` and `object.__setattr__`.
5. Classify residual risks only; do not expand Phase 4 scope.

## Checklist (from P4_00D_SECURITY_REVIEW.md)

- [x] Reproduce the focused adversarial suite on the reviewed head.
- [x] Attempt field mutation using both `dataclasses.replace` and `object.__setattr__`.
- [x] Confirm every rejection produces no adapter call and no output.
- [ ] Confirm CI and CodeQL are green on the evidence PR (attach workflow runs).
- [x] Classify any remaining authority bypass as P0, P1, or lower.
- [x] Produce a separate reviewer report (this document).
- [ ] Complete a review-of-reviewer before closing #43.

## Suite results (reviewed head)

All cases in `test_authority_gate_adversarial.py` were re-executed successfully:

| Attack | Result | Adapter calls |
|--------|--------|---------------|
| Hand-constructed grant (no signature) | REJECTED | 0 |
| Genuine signature copied onto different `grant_id` via `__setattr__` | REJECTED | 0 |
| `replace(decision, policy_version=…)` before `from_decision` | `ValueError` (no grant) | n/a |
| Request claim mismatch (request/resource/agent/context/org/actor/capability/parameters) | REJECTED | 0 |
| Grant metadata `__setattr__` (policy_version, issuer_id, expires_at, grant_id) | REJECTED | 0 |
| Expired grant | REJECTED | 0 |
| Future-dated grant | REJECTED | 0 |
| `ttl_seconds > 300` | `ValueError` at issuance | n/a |
| Raw `AuthorityDecision` to `ExecutionEngine` | REJECTED | 0 |
| Replay same grant | first SUCCEEDED, second REPLAYED | 1 total |
| Reissued grant, same request | first SUCCEEDED, second REPLAYED | 1 total |

### Additional independent probes

| Probe | Result |
|-------|--------|
| `replace(grant, resource="org-b/evil")` then execute | REJECTED; adapter calls 0 |
| `__setattr__(grant, "_signature", "")` | REJECTED; adapter calls 0 |
| `__setattr__(grant, "_signature", "0"*64)` | REJECTED; adapter calls 0 |

**Conclusion on falsification:** No path was found where a mutated or forged
credential produced adapter invocation or non-empty output.

## Boundary mechanics verified

1. **AI-3 decision provenance** — HMAC over canonical decision payload; field
   mutation via `replace` clears effective provenance before grant issuance.
2. **Grant authenticity** — HMAC over full grant payload including issuer,
   grant_id, issued_at, expires_at; `__setattr__` on signed fields invalidates
   `verify()`.
3. **AI-4 type gate** — only `VerifiedAuthorityGrant` is executable; raw
   `AuthorityDecision` is rejected before adapter selection.
4. **Binding** — `grant.binds(request)` ties request identity claims to the
   signed grant.
5. **Lifetime** — inclusive issued / exclusive expiry; max TTL 300s enforced at
   issuance.
6. **Replay** — process-local idempotency on execution id; reissued grants do
   not buy a second adapter call for the same request.

## Residual risks (not P0/P1 for this in-process contract)

| ID | Severity | Description | Owner |
|----|----------|-------------|--------|
| R-01 | P2 / durability | Replay ledger is process-local; crash/restart loses replay memory | **P4-01** Durable Authority & Replay Ledger |
| R-02 | P2 / ops | Absent `DOR_AUTHORITY_SIGNING_KEY` yields ephemeral process key; multi-process share fails closed across restart but is not durable | **P4-01** / ops runbook |
| R-03 | Out of scope | Untrusted code inside the control-plane process | Phase 6 sandbox |
| R-04 | P3 | Callers omitting org/actor claims remain unscoped rather than invented | Product / later authority slices |

No **P0** or **P1** authority bypass of the AI-3 → AI-4 grant boundary was
observed under the attacks above.

## Findings vs implementer claims

The merged remediation matches the attack table in
`P4_00D_SECURITY_REVIEW.md`. Independent re-verification did not contradict
those claims for the in-process HMAC grant model.

Explicit non-claims in the implementer doc (sandbox, durable replay, multi-process
key material) remain valid and are **not** treated as failures of P4-00D.

## Recommendation

| Action | Allowed now? |
|--------|----------------|
| Treat P4-00D code hardening as *adversarially re-verified* on this head | Yes |
| Close #43 | **No** — complete review-of-reviewer |
| Start P4-01 Durable Authority & Replay Ledger coding | **No** until #43 close sequence finishes (per project priority) |
| Attach CI + CodeQL run URLs to this evidence PR | Required before formal approval |

## Review-of-reviewer handoff

A second party should:

1. Spot-check this report against `grants.py` / `execution/engine.py` on the same SHA.
2. Optionally re-run `pytest tests/phase4/p4_00d/test_authority_gate_adversarial.py`.
3. Confirm CI/CodeQL green on main or this evidence branch.
4. Record approval on #43, then close the issue.

---

*End of independent reviewer report.*
