# Governed Patch Review & Apply GUI

## Purpose

The Streamlit flow now continues from a validated Implementation Agent patch proposal to an explicit human review step and the existing governed patch-execution command.

```text
Onboarding intent
      |
Project Audit (advisory/read-only)
      |
Human Requirements + AI-6 proposed plan
      |
Implementation Agent patch proposal
      |
Explicit human diff/scope review
      |
POST /implementation-agent/executions
      |
human implementation.apply_patch capability
      |
stored proposal tenant equality
      |
server-observed workspace baseline
      |
AI-3 exact apply authority
      |
fixed operator lint/test/build toolchain
      |
commit or fail/rollback
```

The GUI does not create a second patch executor. It is a thin review/client layer over the existing `POST /implementation-agent/executions` boundary.

## Upstream provenance

Before rendering an apply action, the GUI revalidates the complete current session chain:

- immutable onboarding intent;
- exact Project Audit identity and repository provenance;
- human requirements and deterministic AI-6 planning fingerprint;
- AI-6 plan content identity;
- exact Implementation Proposal request reconstructed from the current upstream state;
- proposal request fingerprint;
- proposal response command identity and AI-3 `allow`;
- exact unified-diff SHA-256;
- proposal content-addressed ID;
- touched paths and file/change budgets.

A session-mutated plan, proposal request, repository, diff, scope, or proposal ID fails closed before an apply API call.

## Human review

The apply page displays the exact validated unified diff and exact touched paths. Two separate confirmations are required:

1. the operator confirms that the exact diff and touched scope were reviewed;
2. the operator explicitly requests governed patch application and acknowledges that the server may still deny or fail the request.

The review does not grant execution authority. It only permits the GUI to submit the authenticated apply command.

## Minimal browser request

The browser sends only:

```json
{
  "organization_id": "<authenticated tenant>",
  "command_id": "<idempotency key>",
  "proposal_id": "<stored SHA-256 proposal identity>"
}
```

The browser cannot supply:

- a filesystem or workspace path;
- baseline file state or hashes;
- shell text or argv;
- lint/test/build commands;
- environment variables;
- a subset of required checks;
- a replacement diff;
- a caller-selected authority decision.

## Tenant binding

The API first establishes the authenticated organization context and requires the human actor to hold `implementation.apply_patch`.

The same request `organization_id` is then passed into `GovernedPatchExecutionRuntime.run`. The runtime loads the stored proposal and requires its immutable `proposal.request.organization_id` to equal that expected organization before observing workspace state or invoking any tool.

This closes the proposal-ID boundary across tenants: possession or discovery of a proposal ID is not sufficient to apply a proposal created for another organization.

Trusted in-process runtime callers may omit the optional expected organization and continue to use the proposal's own immutable tenant binding. External/API callers assert the authenticated tenant.

## Server-owned baseline and toolchain

At apply time the governed runtime, not the browser:

1. loads the already validated stored proposal;
2. observes the exact current state of every touched workspace path;
3. fingerprints that baseline;
4. binds proposal, proposal request, diff, baseline, toolchain, resource, context packet, and organization into a new `implementation.apply_patch` AI-3 authority question;
5. executes only after AI-3 `ALLOW`;
6. applies the diff in a temporary validation copy;
7. runs the complete operator-fixed lint, test, and build toolchain;
8. verifies that trusted tools did not mutate the approved patch output;
9. rechecks live-workspace drift before commit;
10. commits the exact touched paths atomically as far as the current process contract allows, with in-process rollback on commit failure.

## Result semantics

A successful patch record must have:

- `record_status=succeeded`;
- `committed=true`;
- `rolled_back=false`;
- no error;
- a committed artifact bound to the proposal diff and authority-bound baseline;
- passing evidence for exactly lint, test, and build.

A failed patch record is never treated as applied. It must have `committed=false` and a non-empty error; rollback state is preserved in the response.

The GUI verifies these invariants before storing an apply result in session state.

Trusted-tool success is evidence only. It does not issue DOR's authoritative PASS. P3-20 remains the sole authoritative PASS/FAIL gate.

## Replay and lifecycle limits

The apply command uses a hidden stable command ID for one exact proposal so unchanged resubmission uses the runtime's idempotent replay behavior rather than applying the patch again.

The existing Implementation Agent proposal store and command bindings are still process-local. A process restart can therefore lose stored proposal/replay state. This GUI does not claim crash-safe or distributed proposal/application durability; that remains a later production-hardening boundary.
