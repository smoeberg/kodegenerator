# Implementation Proposal GUI

The Streamlit flow now continues from a validated AI-6 plan into the existing governed Implementation Agent proposal command.

## Flow

```text
Onboarding intent
  -> Project Audit
  -> human requirements
  -> AI-6 proposed plan
  -> exact human file/change scope
  -> POST /implementation-agent/proposals
  -> validated PatchProposal
```

The GUI does **not** expose `POST /implementation-agent/executions` and does not apply repository changes.

## Upstream provenance checks

Before a proposal command can be sent, the dashboard revalidates the complete session chain:

- the onboarding intent is reconstructed canonically;
- Project Audit must still belong to that exact intent and repository;
- `audit_only` remains ineligible for delivery;
- the AI-6 plan must remain `proposed`, `authoritative=false`, and `executable=false`;
- the human requirements are reconstructed and the planning SHA-256 fingerprint is recomputed;
- the AI-6 plan ID is recomputed from the exact plan output so plan steps, rationale, action, resource, confidence, or request fingerprint cannot be silently modified.

The Implementation Agent receives three bounded Context Packet items: planning provenance, human requirements, and the validated AI-6 plan proposal.

## Human scope

The operator must explicitly provide repository-relative file paths and a change budget. The GUI caps one proposal at the current Implementation Agent runtime defaults:

- at most 8 allowed paths / touched files;
- at most 1,000 changed lines.

The server remains authoritative about its configured ceilings and can reject lower operator-specific limits.

The GUI creates a stable hidden command ID for one exact draft. Changing the instruction, plan fingerprint, allowed paths, or budget rotates the command identity. Re-submitting an unchanged successful request therefore uses the Implementation Agent's existing idempotent replay behavior.

## Authority boundary

`POST /implementation-agent/proposals` already requires two independent authority checks:

1. the authenticated actor must hold the organization-scoped `implementation.propose_patch` capability through the Control Plane authority boundary;
2. the digital Implementation Agent must receive a separate AI-3 ALLOW decision for the exact configured repository resource and bounded ImplementationRequest.

Building or displaying the proposal does not grant `implementation.apply_patch`.

Patch application remains a separate command with a separate capability, separate AI-3 question, exact workspace baseline and toolchain binding, and governed patch adapter. That operation is intentionally outside this GUI slice.

## Response validation

The dashboard treats the API result as untrusted transport data and checks that:

- the returned command ID matches the submitted command;
- AI-3 returned `allow`;
- execution and outcome are `succeeded` or `replayed`;
- the proposal ID is SHA-256 shaped;
- every touched path remains inside the human-approved exact scope;
- touched-file and changed-line budgets are not exceeded.

A valid proposal is stored in authenticated Streamlit session state only as downstream provenance. Logout clears the proposal request/result and hidden command identity.
