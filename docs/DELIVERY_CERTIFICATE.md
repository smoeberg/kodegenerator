# Authoritative Delivery Certificate v1

This document defines the canonical authoritative delivery-certification boundary that consumes the non-authoritative `DeliveryVerificationCandidate` introduced by the Delivery Verification Handoff.

## Scope

Delivery Contract v1 answers one bounded question:

> Does this exact content-addressed delivery candidate still match the server-owned governed apply provenance, trusted toolchain, and trusted workspace state?

The answer is persisted as one immutable `DeliveryCertificate` with `result=pass` or `result=fail`.

A delivery certificate is authoritative **only for Delivery Contract v1**. It does not grant execution, merge, release, deployment, or production authority.

## Authoritative inputs

The verifier accepts the candidate payload from the client but does not trust its claims by flag. It first reconstructs `DeliveryVerificationCandidate` and recomputes `candidate_id` from the exact canonical payload.

The backend then checks the candidate against server-owned state:

1. the exact registered governed patch-apply request,
2. the exact immutable patch-execution record,
3. the committed patch artifact and file manifest,
4. the three passing lint/test/build evidence identities,
5. the currently configured trusted toolchain fingerprint,
6. the current trusted tool executable fingerprints,
7. the current trusted workspace file state for every committed path.

No shell command or CI workflow is selected or executed by the certificate endpoint.

## Results

`PASS` requires every Delivery Contract v1 check to match. Its only reason code is `verified`.

`FAIL` is fail-closed and records one or more deterministic reason codes, including:

- `apply_request_mismatch`
- `apply_record_mismatch`
- `artifact_mismatch`
- `evidence_mismatch`
- `toolchain_drift`
- `tool_executable_drift`
- `workspace_drift`

If the server-owned apply provenance cannot be retrieved at all, certification is unavailable (`503`) rather than fabricating either PASS or FAIL.

## Content identity and replay

The certificate binds:

- candidate ID,
- organization and repository,
- apply record ID,
- observed workspace fingerprint,
- Delivery Contract ID/version/fingerprint,
- PASS/FAIL and reason codes,
- certifying authenticated principal,
- certification timestamp.

`certificate_id` is SHA-256 over the canonical certificate content.

Persistence is append-only. Within one organization, `(candidate_id, contract_fingerprint)` is unique, so the same candidate under the same contract cannot later receive a contradictory certificate. `command_id` is also unique per organization for idempotent command replay.

## API

Canonical authenticated endpoints:

- `POST /api/v1/control-plane/delivery-certificates`
- `GET /api/v1/control-plane/delivery-certificates/{certificate_id}?organization_id=...`

Certification is an explicit organization-admin action in v1. Reading an existing certificate requires normal authenticated runtime membership in the requested organization.

## Persistence

Migration `028_delivery_certificates` adds the append-only `delivery_certificates` table.

The table is tenant-scoped and PostgreSQL RLS is both enabled and forced using the existing `dor.organization_id` transaction context.

## Explicit non-capabilities

A PASS certificate does **not**:

- create a Git branch or commit,
- push to a remote,
- open or merge a pull request,
- start GitHub Actions,
- publish an artifact,
- release a version,
- deploy software,
- grant another actor or agent authority.

Those remain separate governed boundaries.
