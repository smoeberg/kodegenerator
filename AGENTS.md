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

## Change protocol

- Search for an existing canonical component before creating a new model,
  service, agent, migration hierarchy, or runtime path.
- Create changes on a separate branch from the fetched `origin/main`; never
  write directly to `main`.
- Preserve one canonical runtime identity and extend existing boundaries where
  possible.
- Keep the diff within the requested scope and add executable tests.
- Run `python scripts/repository_state.py --base origin/main --validate`, the
  relevant tests, and `python scripts/ci_merge_gate.py --base origin/main
  --head HEAD` before publication.
- Report exact commit SHAs and distinguish locally run checks from CI results.

## Prohibited behavior

- Do not use conversation history as the source of truth for repository state.
- Do not invent files, commits, test results, PRs, or merge status.
- Do not duplicate canonical architecture because an older audit proposes a
  different directory or class name.
- Do not continue when the target repository, branch, or relevant source files
  cannot be read.
