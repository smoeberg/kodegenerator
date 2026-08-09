# Phase 4B-1 — Governed Implementation Agent

## Purpose

This specialist-agent runtime can propose a text patch from an immutable,
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

The operational entrypoint is the authenticated
`POST /implementation-agent/proposals` command. It first requires the invoking
human or service actor to hold the organization-scoped
`implementation.propose_patch` capability. The downstream digital agent then
passes a separate AI-3 policy decision bound to an operator-configured exact
repository resource. Neither decision substitutes for the other.

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

`OpenAIImplementationProvider` is the first concrete provider. It uses one
operator-selected model and the fixed OpenAI Responses endpoint, disables
provider-side storage, requires strict structured output, and receives only the
already bounded `ImplementationRequest`. Tests continue to use a deterministic
provider keyed by the exact request fingerprint and an injected transport for
the OpenAI envelope.

Provider configuration is fail-closed. The API command is unavailable until an
operator supplies `OPENAI_API_KEY`, `DOR_IMPLEMENTATION_MODEL`, and exact
`DOR_IMPLEMENTATION_ALLOWED_RESOURCES`. Runtime ceilings independently cap
files, changed lines, Context Packet items, Context Packet bytes, provider input
bytes, and provider output bytes. Sensitive Context Packet items remain denied
until an explicit operator policy for that data class is implemented.

## Command identity and replay

The API `command_id` becomes the AI-4 idempotency key and is permanently bound
in the process runtime to one `ImplementationRequest` fingerprint. Reusing it
for changed instructions, context, scope, resource, or budgets fails with a
conflict. Reusing it for the same request returns an AI-4 replay and never calls
the provider again.

This state is intentionally process-local until Phase 4D durable governance is
implemented. It is not yet crash-safe or distributed idempotency.

## Patch contract

The accepted first-slice format is a deliberately narrow Git unified text diff:

- every section has `diff --git`, `---`, `+++`, and at least one hunk;
- paths are canonical, repository-relative POSIX paths;
- touched paths must be in the exact approved scope;
- duplicate file sections, renames, traversal, and binary patches are rejected;
- file and changed-line budgets are enforced;
- proposal and diff identities are SHA-256 content addresses.

## Explicit non-responsibilities

The current operational slice does not:

- write, create, rename, or delete repository files;
- apply a patch;
- execute shell commands;
- run linters, tests, containers, or agent-selected network calls;
- retry a provider failure;
- grant authority or bypass AI-3;
- mutate AI-1 identity, AI-2 context, or AI-5 outcomes.

Patch application and deterministic verification belong to the later governed
sandbox slice.
