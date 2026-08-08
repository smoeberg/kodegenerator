# Phase 4B — Project Audit Agent

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

The operational application layer supplies that proof through
`GitRepositoryManifestBuilder`. It resolves one exact commit, lists its complete
tracked tree, and rejects any tracked working-tree drift before the collector
reads repository bytes. Untracked files are outside the revision and therefore
outside the evidence bundle.

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

## Operational command and providers

The read-only command executes the complete AI-1 through AI-5 chain and writes
artifacts only after the report passes evidence validation:

```bash
python -m phase4.project_audit audit \
  --repository-root . \
  --provider baseline
```

The deterministic `baseline` provider establishes DOR's reproducible minimum
integrity assessment. It makes no network calls and reports only fixed,
machine-checkable observations.

The opt-in `openai` provider sends the bounded evidence bundle through the
OpenAI Responses API using strict Structured Outputs. It requires both
`OPENAI_API_KEY` and either `--model` or `DOR_PROJECT_AUDIT_MODEL`. The API key
is used only in the authorization header and is never included in request
identity, prompts, reports, or errors. The provider fails instead of silently
truncating an oversized complete evidence bundle.

```bash
python -m phase4.project_audit audit \
  --repository-root . \
  --provider openai \
  --model <approved-model>
```

JSON and Markdown artifacts include the exact commit, manifest, bundle,
request, report, AI-3 decision, AI-4 execution, and AI-5 outcome identities.
They remain advisory and do not mutate repository source.

## Explicit non-goals

The Project Audit Agent does not:

- write or patch repository files;
- execute tests, commands, deployments, or migrations;
- choose a model or silently fall back between providers;
- replace P3-20 deterministic verification;
- turn an agent claim into authority;
- declare production readiness from package-level tests alone.
