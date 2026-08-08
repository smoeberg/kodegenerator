# Phase 4B-2 — Project Audit Agent

## Purpose

The Project Audit Agent provides a critical, repository-wide assessment before
DOR chooses another development slice. It exists to detect the difference
between a locally correct package and a coherent, usable system.

```text
trusted revision manifest + AI-2 project context
                    |
              AI-3 exact authority
                    |
          AI-4 project-audit adapter
                    |
       evidence-backed advisory report
                    |
         P3-20 remains PASS/FAIL gate
```

The report is advisory. It may recommend `CONTINUE`, `CONTINUE_WITH_GAPS`,
`REPLAN`, or `ESCALATE`. It cannot issue `PASS` or `FAIL`, authorize execution,
change code, run commands, or approve its own evidence.

## Evidence boundary

A trusted application supplies a complete `RepositoryManifest` bound to a
specific commit SHA. Each manifest entry contains an exact repository-relative
path and SHA-256. `ProjectEvidenceCollector`:

- invokes neither Git nor shell;
- rejects traversal, symlinks, missing files, directories, and hash drift;
- enforces explicit file and byte limits without silently truncating;
- classifies each artifact and retains UTF-8 text when available;
- returns an immutable, content-addressed `ProjectEvidenceBundle` only when
  every manifest entry was observed exactly.

Manifest generation and proof that the declared manifest is the complete Git
tree are application responsibilities outside the agent boundary.

## Authority and execution binding

`ProjectAuditRequest` binds the registered agent, repository resource, AI-2
context packet, evidence bundle, audit objectives, and target maturity. Its
fingerprints are included in the exact AI-3 authority question. The statically
registered AI-4 adapter reconstructs that request before calling a provider.

A declared audit capability is not authority. `DENY`, missing authority, an
unregistered request, or any binding mismatch prevents the provider call.

## Report validation

Provider output is untrusted. Every finding must be labelled `FACT`,
`INFERENCE`, or `UNKNOWN` and contain machine-checkable evidence assertions.
The contract currently supports exact path existence/absence, text
presence/absence, and SHA-256 equality. An assertion that is false for the
bound evidence bundle rejects the entire report.

Every report assesses all five maturity levels:

1. `CONTRACT_COMPLETE`
2. `INTEGRATED`
3. `OPERATIONAL`
4. `E2E_VERIFIED`
5. `PRODUCTION_READY`

The validator also prevents a provider from understating validated high or
critical risks with an overly permissive recommendation. Semantic judgment
beyond the supported predicates remains advisory and must be independently
reviewed.

## Explicit non-goals

This slice does not:

- write or patch repository files;
- execute tests, commands, deployments, or migrations;
- call a concrete model SDK or choose a model;
- replace P3-20 deterministic verification;
- turn an agent claim into authority;
- declare production readiness from package-level tests alone.
