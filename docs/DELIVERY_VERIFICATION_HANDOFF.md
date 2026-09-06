# Delivery Verification Handoff

This document defines the content-addressed, non-authoritative handoff from a successful governed patch apply to the authoritative Delivery Contract v1 boundary.

## Why the handoff itself is not PASS

The handoff artifact remains deliberately unable to express PASS/FAIL. It packages exact validated provenance and has one lifecycle state:

- `pending_authoritative_verification`

It is always:

- `authoritative = false`
- `verification_result = null`

The separate Delivery Certificate API introduced after this handoff consumes the candidate and publishes the authoritative Delivery Contract v1 result. The candidate itself never gains that authority retroactively.

## Trust boundary

The handoff is derived only after the dashboard revalidates the complete chain:

1. immutable onboarding intent,
2. advisory Project Audit provenance,
3. human requirements and immutable AI-6 plan proposal,
4. governed Implementation Agent patch proposal,
5. governed patch execution with `record_status=succeeded`,
6. `committed=true` and `rolled_back=false`,
7. exact committed patch artifact,
8. passing lint, test and build evidence.

A truthy session flag is insufficient. Before creating the handoff the dashboard recomputes and checks:

- the committed `artifact_id`,
- each stdout/stderr log artifact identity,
- each tool evidence identity,
- the final patch `record_id`.

The candidate then content-addresses the validated provenance again into `candidate_id`.

## Candidate binding

`candidate_id` binds at least:

- organization and exact repository,
- onboarding intent ID and content fingerprint,
- audit report/request/manifest/evidence IDs and audited commit,
- AI-6 plan ID and request fingerprint,
- proposal ID and proposal request fingerprint,
- apply record ID and apply request fingerprint,
- committed artifact ID and proposal diff SHA-256,
- authority-bound baseline fingerprint,
- operator-fixed toolchain fingerprint,
- exact committed file states,
- the three content-addressed lint/test/build evidence IDs.

Any change to those inputs yields a different candidate or fails reconstruction.

## Authoritative consumer

`POST /api/v1/control-plane/delivery-certificates` is the canonical consumer of the handoff.

Before issuing PASS/FAIL, the backend reconstructs the candidate and cross-checks it against server-owned governed apply provenance, the configured trusted toolchain/executables, and the current trusted workspace file state. The resulting immutable certificate is persisted under migration `028_delivery_certificates`.

See `docs/DELIVERY_CERTIFICATE.md` for the authoritative contract.

## Explicit non-capabilities

Creating a handoff does **not**:

- issue delivery PASS/FAIL,
- create a Git commit or branch,
- push to a remote,
- open or merge a pull request,
- start GitHub Actions or another CI system,
- select shell commands or verification tools,
- release or deploy an artifact,
- grant execution, release or deployment authority.

The Delivery Certificate boundary also does not grant release/deploy authority; it only publishes the authoritative result for Delivery Contract v1.

## Current-state relationship

The handoff supplied the immutable candidate/provenance boundary. `delivery_certificate` is closed only by the separate authoritative Delivery Certificate v1 implementation; the handoff remains the required preceding artifact.
