# Repository-first agent protocol

This file is the mandatory operating contract for every human-operated or
autonomous coding agent working in this repository.

## Authority order

Current repository evidence has this precedence:

1. fetched `origin/main`
2. the active pull-request head
3. production code, tests, migrations, and CI configuration
4. `docs/CURRENT_STATE.json` and other repository documentation
5. conversations, memories, audit reports, and roadmaps

Memory is historical context, never evidence of current implementation state.

## Mandatory preflight

Before analysis, planning, or mutation, run:

```bash
git fetch origin --prune
python scripts/repository_state.py --base origin/main --validate
```

The response or pull-request description must state the active branch, HEAD,
`origin/main`, ahead/behind counts, dirty state, and canonical Alembic head.
If fetch or validation cannot be completed, stop and label repository status
`UNKNOWN`; do not infer it from memory.

## Evidence labels

Material status claims must be classified as:

- `VERIFIED`: observed in the fetched repository, CI, or GitHub state
- `INFERRED`: derived from verified evidence but not directly proven
- `STALE`: present only in older documentation, audit, or memory
- `UNKNOWN`: not accessible or not verified

Never call a phase missing, complete, green, or merged from memory alone.

## Development Governance v0

For changes after governance boundary
`7f91611e2a3f0bf81449551f72a85418f3f27e3d`, the mandatory development-
governance contract is `docs/GOVERNANCE_V0.md` and the executable routing
surface is `phase4.development_governance`.

WQ-101 through WQ-104 are explicitly grandfathered. This prospective rule does
not retroactively invalidate their approved artifacts.

Semantic changes must not move directly from one proposing agent to coding.
They must be routed automatically through the Governance v0 sequence:

```text
ProblemBrief
-> Product Owner problem approval
-> Orchestrator design
-> Product Owner exact solution approval
-> Coder
-> deterministic Evidence Gate
-> Auditor proof/conformance verification
-> Independent Reviewer
```

The Human Owner is not the normal prompt router or scheduler for these roles.
`GovernanceCoordinator` owns sequencing once distinct role providers are bound.

A semantic change is any change to domain meaning, lifecycle/state transitions,
persisted meaning, consistency or concurrency guarantees, dependency semantics,
authority boundaries, acceptance invariants, explicit non-goals, or approved
scope. If an agent cannot determine whether one of those dimensions changes,
it must fail closed to the semantic gates. Ordinary technical difficulty is
not an escalation.

Mechanical work may use the safe harbor only when it preserves the exact
approved observable contract. Scope expansion discovered during design returns
to a newer ProblemBrief; it cannot be silently approved only at the solution
gate.

No claimed artifact fact may be promoted to review merely from a coder report.
Source-of-truth identity, lineage, diff, tests, CI/migration/dependency evidence
must be checked deterministically where possible. The Auditor owns the semantic
residue, including whether proof construction actually exercises its claimed
invariant and whether the artifact conforms to the exact approved solution.

## Change protocol

- Search for an existing canonical component before creating a new model,
  service, agent, migration hierarchy, or runtime path.
- Create changes on a separate branch from the fetched approved base; never
  write directly to `main`. When a governed WorkUnit supplies an exact approved
  integration/base SHA, that immutable SHA is the base for that WorkUnit.
- Preserve one canonical runtime identity and extend existing boundaries where
  possible.
- Keep the diff within the requested scope and add executable tests.
- Run `python scripts/repository_state.py --base origin/main --validate`, the
  relevant tests, and `python scripts/ci_merge_gate.py --base origin/main
  --head HEAD` before publication where those checks apply to the target branch.
- Report exact commit SHAs and distinguish locally run checks from CI results.

## Prohibited behavior

- Do not use conversation history as the source of truth for repository state.
- Do not invent files, commits, test results, PRs, or merge status.
- Do not duplicate canonical architecture because an older audit proposes a
  different directory or class name.
- Do not continue when the target repository, branch, or relevant source files
  cannot be read.
- Do not bypass Development Governance v0 by asking the Human Owner to manually
  relay routine Product Owner, Auditor, Reviewer, or Coder prompts.
