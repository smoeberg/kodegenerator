# Requirement → Artifact Traceability v1

## Purpose

Requirement Traceability v1 closes the `requirement_to_artifact_coverage` roadmap gap without converting structural trace links into semantic verification.

The flow is:

`human planning declaration -> AI-6 plan fingerprint -> governed proposal/apply -> PASS Delivery Certificate -> immutable requirement traceability manifest`

A traceability manifest answers:

- which exact human planning source text was used;
- which PASS delivery certificate and candidate root the trace;
- which committed artifact paths are linked to each source item;
- which certified lint/test/build evidence IDs were explicitly linked as supporting evidence;
- whether every source requirement has at least one artifact link.

It deliberately does **not** answer whether the requirement is semantically satisfied.

## Source requirements

v1 does not parse, summarize, rewrite, or reinterpret the user's free-form requirements. It derives at most three exact source items from the already content-addressed planning declaration:

1. `objective`
2. `acceptance_criteria`
3. `constraints` when non-empty

Each source receives a deterministic `requirement_id` bound to the existing AI-6 `plan_request_fingerprint` and the exact source text.

The backend recomputes the existing Project Planning fingerprint from the submitted requirements plus canonical planning provenance and requires it to equal the `plan_request_fingerprint` already embedded in the delivery candidate. This makes later requirement substitution fail closed.

## Root of trust

Creation requires an existing authoritative Delivery Contract v1 certificate with `result=pass`.

The backend loads the certificate and candidate from PostgreSQL. It does not trust a browser-supplied certificate/candidate substitute. Before accepting links it:

- recomputes the persisted certificate content identity;
- reconstructs the persisted delivery candidate;
- verifies certificate → candidate binding;
- verifies candidate → AI-6 plan identity;
- recomputes requirements + planning provenance → plan fingerprint;
- restricts artifact links to paths in the certified candidate file manifest;
- restricts evidence links to evidence IDs in the certified candidate.

Unknown paths, unknown evidence IDs, plan drift, provenance drift, FAIL certificates, tenant drift, and content-ID drift are rejected.

## Coverage semantics

A link is a human-declared relevance relation whose referenced IDs are server-validated.

`linked=true` means the requirement source references one or more certified artifact paths.

`evidenced=true` means it references both one or more certified artifact paths and one or more certified tool-evidence IDs.

Manifest status is:

- `complete`: every source requirement has at least one artifact link;
- `partial`: at least one source requirement has no artifact link.

These statuses are traceability completeness only. Every manifest includes:

```json
{
  "reference_integrity_verified": true,
  "authoritative": false,
  "semantic_result": null,
  "release_authority": false
}
```

A `complete` manifest must never be interpreted as semantic acceptance, release approval, merge approval, deployment authority, or execution authority.

## Persistence

Migration `029_requirement_traceability` adds `requirement_traceability_manifests`.

The table is:

- append-only through the supported API;
- tenant-scoped;
- protected by forced PostgreSQL row-level security;
- content-addressed by `manifest_id`;
- idempotent per `(organization_id, command_id)`.

Multiple distinct immutable manifests may refer to the same PASS certificate. This supports corrected trace mappings without rewriting history. Any downstream acceptance/release contract must reference one exact `manifest_id`; it must never infer "latest" as authority.

## API

Authenticated canonical endpoints:

- `POST /api/v1/control-plane/requirement-traceability`
- `GET /api/v1/control-plane/requirement-traceability/{manifest_id}?organization_id=...`

Creation requires organization-admin membership in v1. Read access requires normal authenticated runtime membership in the selected organization.

## GUI

After a PASS Delivery Certificate, Streamlit exposes `Requirement → Artifact Traceability`.

For each exact source requirement, the user can select only:

- artifact paths present in the delivery candidate; and
- optional evidence IDs present in the delivery candidate.

The GUI uses a stable hidden command ID for an unchanged draft and rotates it whenever the exact trace mapping changes. The returned manifest is reconstructed and content-ID validated before being stored in session state.

Logout clears all traceability draft/result state.

## Explicit non-goals

v1 does not:

- infer semantic requirement satisfaction;
- split free-form acceptance criteria into invented sub-requirements;
- run new tests or CI;
- mutate the repository;
- issue release/deploy/merge authority;
- select a canonical manifest by recency;
- perform multi-spec acceptance.

The next separate boundary is `multi_spec_verified_artifact_acceptance`, which may consume an exact PASS delivery certificate plus an exact traceability `manifest_id` under its own explicit verification contract.
