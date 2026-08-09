# Phase 4B-1 — Governed Implementation Agent

## Purpose

This specialist-agent runtime can propose a text patch from an immutable,
bounded context packet and can apply an already validated proposal through a
separate governed execution command. It exposes no general-purpose execution
facility.

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

Patch application is a second chain with a distinct capability and authority
question:

```text
validated PatchProposal
        |
human implementation.apply_patch capability
        |
AI-3 exact apply authority (proposal + baseline + toolchain)
        |
AI-4 governed patch adapter
        |
AI-5 immutable outcome and non-authoritative tool evidence
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

## Governed patch execution

The authenticated `POST /implementation-agent/executions` command accepts only
an organization, command ID, and stored proposal ID. It never accepts argv,
shell text, tool paths, environment variables, or a caller-selected subset of
checks. The operator configures the exact workspace and complete lint/test/build
toolchain when the process starts.

Before AI-3 evaluates the apply action, the runtime observes the exact touched
file states and binds their fingerprint, the proposal, diff, Context Packet,
and toolchain fingerprint into the authority request. AI-4 rejects workspace
drift before any tool runs and again immediately before commit.

The adapter copies the bounded workspace into a temporary validation area,
applies the already validated diff there with a fixed Git executable, and runs
the fixed tools with `shell=False`, timeouts, bounded captured logs, and a
minimal environment. The Python adapter injects a process-ephemeral test-only
JWT key instead of exposing the DOR process secret to project code. Tool side
effects are discarded with that copy. Only when all three evidence classes pass
does the adapter atomically replace the exact approved live paths. An in-process
commit failure restores every touched path from its authority-bound baseline.

Artifacts, file manifests, logs, tool evidence, patch records, AI-4 executions,
and AI-5 outcomes are immutable and content-addressed. Tool success is evidence
only: it does not issue DOR's authoritative PASS. P3-20 remains the sole
PASS/FAIL authority.

Command replay is process-local and bound to one proposal and its original
authority-bound baseline. A replay neither applies the patch nor runs tools
again. Rebinding a command ID to another proposal fails with a conflict.

## Explicit non-responsibilities

The current operational slice does not:

- execute a shell or accept caller/agent-supplied commands;
- run agent-selected network calls;
- allow callers to omit an operator-required lint/test/build class;
- retry a provider failure;
- grant authority or bypass AI-3;
- mutate AI-1 identity, AI-2 context, or AI-5 outcomes.

The temporary workspace is process isolation from the live checkout, not an OS
security sandbox. It does not provide container namespaces, network isolation,
distributed locking, crash-safe multi-file transactions, or durable replay.
Those remain Phase 4D/Phase 6 production-hardening responsibilities.
