# DOR Development Governance v0

Version: `governance-v0`

Effective boundary: `7f91611e2a3f0bf81449551f72a85418f3f27e3d`

WQ-101 through WQ-104 are grandfathered as the approved baseline under the
process that was valid when they were produced. Governance v0 applies
prospectively after the boundary; it does not retroactively invalidate those
artifacts or their reviews.

## Purpose

Governance v0 separates four questions that must not collapse into one
intelligent role:

1. **Product Owner:** should this problem/design change DOR?
2. **Orchestrator:** how should an approved problem be investigated and designed?
3. **Auditor:** are repository/evidence/conformance claims actually true?
4. **Independent Reviewer:** does the verified artifact satisfy the approved contract?

The Coder implements an approved solution. The Human Owner is not a routine
prompt router or scheduler.

## Authority invariants

- A role that proposes a semantic change cannot be the sole authority approving it.
- Product Owner approval never proves repository facts.
- Auditor verification never decides whether architecture is desirable.
- Independent Review never rewrites approved scope or acceptance criteria.
- Intelligent Product Owner, Orchestrator, Coder, Auditor, and Reviewer providers
  use distinct provider identities in one governed run.
- Human Owner escalation is reserved for charter changes, fundamental product
  direction, high-impact/irreversible choices, or unresolved product intent.

## Discovery, problem gate, design, solution gate

The governed semantic flow is:

`discovery -> ProblemBrief -> PO -> design -> SolutionProposal -> PO -> coder -> evidence -> auditor -> reviewer`

Discovery may inspect repository facts, constraints and options. It may not
commit DOR to new semantics.

### Problem gate

`ProblemBrief` contains the observed problem, evidence references, impact,
affected concepts, constraints, non-goals and proposed scope.

Product Owner returns one of:

- `APPROVED_FOR_DESIGN`
- `REJECTED`
- `DEFERRED`
- `CLARIFICATION_NEEDED`

An approval is bound to the exact complete ProblemBrief fingerprint and locks
`approved_scope`, constraints and explicit non-goals.

### Solution gate

`SolutionProposal` is bound to the exact ProblemApproval and must repeat its
approved scope and explicit non-goals. It declares either:

- `WITHIN_APPROVED_SCOPE` with no scope delta; or
- `SCOPE_EXPANSION_REQUIRED` with an explicit scope delta.

Product Owner actively checks problem alignment, scope and non-goals before
returning `APPROVED_FOR_IMPLEMENTATION`. Scope expansion returns to a newer
version of the ProblemBrief; GOV-104 cannot silently bypass GOV-103.

Approval is bound to the exact complete SolutionProposal fingerprint. A
materially changed proposal requires a new approval.

## Mechanical safe harbor

Technical complexity is not a Product Owner escalation by itself.

Work remains mechanical when it preserves the exact approved observable
contract and does not change any of:

- domain meaning
- lifecycle/state transitions
- persisted meaning
- consistency guarantee
- concurrency guarantee
- dependency semantics
- authority boundary
- acceptance invariant
- explicit non-goal
- approved scope

`UNCERTAIN` means specifically: the Orchestrator cannot determine whether one
of those semantic dimensions changes. In that case it fails closed to the
semantic gates. Ordinary implementation uncertainty does not escalate.

## Evidence Gate Core

The deterministic evidence layer should verify source-of-truth facts wherever
possible, including exact artifact/base identity, refs, diff, tests, CI,
migration facts and dependency versions.

The Auditor handles the semantic residue that deterministic tooling cannot
establish, especially whether a test construction actually exercises the
claimed invariant and, once a SolutionProposal exists, whether the artifact
conforms to that approved design.

Auditor output is only `VERIFIED` or `VETO`. A `VERIFIED` result requires both
proof-construction verification and solution-conformance verification.

## Independent review

Reviewer input is the approved problem/solution contract, exact artifact and
verified evidence. Coder conversation and persuasive Orchestrator reasoning are
not part of the review contract. Reviewer returns `APPROVED` or `REJECTED`.

## Automatic routing

`GovernanceCoordinator` owns role sequencing. Human Owner does not manually
copy prompts between Product Owner, Orchestrator, Coder, Auditor and Reviewer.
Role providers are injected using the same provider-neutral pattern already
used by the Council orchestrator; the coordinator is fail-closed and does not
create a new scheduler or Authority engine.

## Measurement, not optimization

Governance v0 records a small process-local measurement surface:

- `gate_round_trip_count`
- `classification_count`
- `uncertainty_escalation_count`
- `uncertainty_escalation_rate`
- `po_response_latency`
- `scope_expansion_count`
- `semantic_find_count`
- `auditor_veto_count`
- `governance_blocked_time`

Metrics do not affect routing. They exist so governance itself can later be
measured and removed or tightened if it proves to be friction without findings.

## Scope guard

Governance v0 intentionally has no new database tables, migrations, scheduler,
persistent decision graph, event-sourcing subsystem, automatic optimization or
new organization-governance model.
