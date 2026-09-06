# Delivery Verification Handoff

This document defines the first concrete slice of the open `delivery_certificate` work item: a content-addressed, non-authoritative handoff from a successful governed patch apply to a future authoritative delivery gate.

## Why this is a handoff, not PASS

The current repository has a Phase 4 epistemic verification subsystem, but that subsystem evaluates verifier observations and deliberately does not grant execution authority. The current API surface also has no canonical delivery-verification command that the dashboard can invoke.

The dashboard therefore must not invent a `/verify` endpoint, run shell/CI commands from the browser, or reinterpret successful lint/test/build evidence as an authoritative delivery PASS.

A Delivery Verification Candidate has exactly one lifecycle state:

- `pending_authoritative_verification`

It is always:

- `authoritative = false`
- `verification_result = null`

The candidate itself cannot express PASS or FAIL.

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

Those capabilities require separate governed contracts and transports.

## Current-state relationship

`docs/CURRENT_STATE.json` still lists `delivery_certificate` as open work. This handoff intentionally does not mark that item complete: it supplies the immutable candidate/provenance boundary that a later authoritative delivery-certification implementation can consume.

Until that later boundary exists, the only correct UI state after handoff creation is **PENDING authoritative verification**.
