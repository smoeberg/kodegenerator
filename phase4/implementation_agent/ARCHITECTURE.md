# Phase 4B-1 — Governed Implementation Agent

## Purpose

This first specialist-agent slice can propose a text patch from an immutable,
bounded context packet. It cannot apply the patch or invoke any general-purpose
execution facility.

```text
AI-1 registered identity
        |
AI-2 bounded context packet
        |
AI-3 exact proposal authority
        |
AI-4 implementation adapter
        |
AI-5 immutable outcome
```

## Authority binding

`ImplementationRequest` binds:

- agent identity and role;
- repository resource;
- exact AI-2 context packet identity;
- implementation instruction;
- exact allowed repository-relative paths;
- maximum touched files and changed lines.

The content-addressed request fingerprint and scope fingerprint are included in
the AI-3 authority question. The AI-4 request ID is derived from that exact
question. The implementation adapter independently reconstructs the expected
request and rejects any mismatch before invoking a provider.

Building an `AuthorityRequest` is not an authority decision. Only AI-3 may
produce `ALLOW` or `DENY`, and AI-4 still requires the resulting exact decision.

## Provider boundary

`ImplementationProvider` is intentionally provider-neutral. It receives only an
immutable `ImplementationRequest` and returns an untrusted `PatchCandidate`.
The adapter validates that candidate before recording a `PatchProposal`.

Concrete OpenAI, Anthropic, local-model, and model-routing integrations are
outside this slice. Tests use a deterministic fake provider keyed by the exact
request fingerprint.

## Patch contract

The accepted first-slice format is a deliberately narrow Git unified text diff:

- every section has `diff --git`, `---`, `+++`, and at least one hunk;
- paths are canonical, repository-relative POSIX paths;
- touched paths must be in the exact approved scope;
- duplicate file sections, renames, traversal, and binary patches are rejected;
- file and changed-line budgets are enforced;
- proposal and diff identities are SHA-256 content addresses.

## Explicit non-responsibilities

Phase 4B-1 does not:

- write, create, rename, or delete repository files;
- apply a patch;
- execute shell commands;
- run linters, tests, containers, or network calls;
- select or configure production models;
- retry a provider failure;
- grant authority or bypass AI-3;
- mutate AI-1 identity, AI-2 context, or AI-5 outcomes.

Patch application and deterministic verification belong to the later governed
sandbox slice.
