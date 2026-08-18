# P4-00D Authority Boundary Security Review

Status: **READY FOR INDEPENDENT REVIEW — NOT YET APPROVED**

Issue: [#43 — P4-00 Cross-Agent Authority Verification](https://github.com/smoeberg/kodegenerator/issues/43)

## Scope

This slice adversarially tests and hardens the AI-3 to AI-4 boundary introduced
by P4-00C. It does not expand Phase 4 features and does not authorize Phase 5.

Reviewed production seams:

- `phase4.authority.AuthorityEngine`
- `phase4.authority.VerifiedAuthorityGrant`
- `phase4.execution.ExecutionEngine`
- `phase4.execution.GovernedDispatch`

Adversarial suite:

- `tests/phase4/p4_00d/test_authority_gate_adversarial.py`

## Finding and remediation

The earlier object-identity token rejected a hand-constructed grant, but it did
not authenticate the copied fields of a genuine object. It also had no issuer,
grant identity, or lifetime.

The remediation replaces field-presence trust with a canonical HMAC signature.
AI-3 signs its complete decision. A grant can only be issued from a decision
whose signature still verifies, and AI-4 verifies the complete grant before it
creates a governed dispatch.

The signed grant covers:

- request, agent, action, resource, and context packet identities;
- organization, actor, and capability claims when supplied by the caller;
- canonical execution parameters;
- policy ID, policy version, and matched rule IDs;
- decision, issuer, unique grant ID, issued-at, and expires-at.

The maximum grant lifetime is five minutes. Future-dated and expired grants are
rejected before adapter invocation.

## Adversarial evidence

| Attack | Expected result |
|---|---|
| Hand-constructed grant | REJECTED; no adapter call |
| Signature copied to a different grant | REJECTED; no adapter call |
| Signed AI-3 decision modified before grant issuance | Grant issuance rejected |
| Request, resource, agent, or context mismatch | REJECTED; no adapter call |
| Organization, actor, or capability mismatch | REJECTED; no adapter call |
| Parameter fingerprint mismatch | REJECTED; no adapter call |
| Policy, issuer, expiry, or grant ID tampering | REJECTED; no adapter call |
| Expired or future-dated grant | REJECTED; no adapter call |
| Raw AuthorityDecision submitted to AI-4 | REJECTED; no adapter call |
| Same request with same or reissued grant | REPLAYED; one adapter call total |

Local focused verification:

```text
58 passed
```

Repository CI and CodeQL evidence must be linked from the pull request before
approval.

## Operational key contract

`DOR_AUTHORITY_SIGNING_KEY` may contain a URL-safe base64 key that decodes to
at least 32 bytes. Operators must provide the same secret to every trusted AI-3
and AI-4 process that exchanges grants.

If the variable is absent, DOR creates a process-local ephemeral key. This is
safe for the current single-process runtime and fails closed across restarts,
but it is not a durable multi-process configuration.

## Residual risks and explicit non-claims

1. Arbitrary untrusted Python executing inside the control-plane process is
   outside this in-process contract and must be isolated by the Phase 6 sandbox.
2. Replay storage remains process-local. Crash-safe replay prevention belongs to
   the durability slice and is not claimed here.
3. Organization and actor claims are cryptographically bound when present.
   Existing callers that do not yet provide those claims remain visibly
   unscoped rather than receiving invented identities.
4. This report was prepared with the implementation and is not independent
   reviewer evidence.

## Independent reviewer checklist

- [ ] Reproduce the focused adversarial suite on the PR head.
- [ ] Attempt field mutation using both `dataclasses.replace` and
      `object.__setattr__`.
- [ ] Confirm every rejection produces no adapter call and no output.
- [ ] Confirm CI and CodeQL are green.
- [ ] Classify any remaining authority bypass as P0, P1, or lower.
- [ ] Produce a separate reviewer report.
- [ ] Complete a review-of-reviewer before closing #43.

P4-00 remains open until those independent steps are complete.
