# JWT signing-key rotation runbook

This runbook rotates API JWT HMAC keys without allowing an unknown key to fall
back to the active signer. Store every value in the deployment secret manager,
not in repository files or command history.

## Preconditions

- All API replicas run a version that issues and verifies the protected `kid`
  header.
- The maximum configured access-token lifetime is known.
- The new HMAC secret contains at least 32 random characters.
- The deployment mechanism updates every API replica atomically or supports a
  controlled rolling overlap.

## Rotation

Assume `2026-08` is active and `2026-09` is the new key.

1. Add both secrets to `DOR_JWT_SIGNING_KEYS`; keep `2026-08` active.
2. Deploy and verify every replica accepts a token carrying `kid=2026-08`.
3. Change `DOR_JWT_ACTIVE_KEY_ID` to `2026-09` while retaining both keys.
4. Deploy and verify new tokens carry `kid=2026-09`; old tokens must still
   work during this overlap.
5. Wait at least the maximum access-token lifetime plus deployment clock skew.
6. Add `2026-08` to `DOR_JWT_REVOKED_KEY_IDS` and deploy.
7. Verify old tokens return HTTP 401 and new tokens remain valid.
8. Remove the old secret only after all replicas have loaded the revocation.

Example logical configuration (values must come from the secret manager):

```text
DOR_JWT_SIGNING_KEYS={"2026-08":"<old-secret>","2026-09":"<new-secret>"}
DOR_JWT_ACTIVE_KEY_ID=2026-09
DOR_JWT_REVOKED_KEY_IDS=2026-08
```

## Emergency revocation

If a verification key is compromised, switch issuance to a known-good key and
add the compromised ID to `DOR_JWT_REVOKED_KEY_IDS` in the same deployment.
This intentionally invalidates every token signed by the compromised key.
Never revoke the active key without switching the active ID first: startup
rejects that configuration.

## Rollback

During the overlap window, roll back by selecting the previous non-revoked key
as active. After a key has been declared compromised or revoked, do not make it
active again; issue a new key ID and require affected users to authenticate
again. Configuration errors are startup failures rather than degraded-mode
fallbacks.
