# Production hardening baseline

Baseline date: 2026-08-29
Baseline commit: `a2587e9` (merged PR #135)

The `remediation/production-hardening` branch was created directly from the
current `origin/main`. The older local `integration/phases1-5` branch is
retained for history and is not a merge source.

Verified before remediation:

- Python compilation succeeded for production and test modules.
- `git diff --check` succeeded.
- The Alembic graph had one head: `013_terminal_side_effects`.
- No source diff existed between the branch and `origin/main`.

The full pytest suite was not rerun locally because the execution image did not
provide pytest or the repository dependencies. CI remains the authoritative
full-suite gate; this limitation must not be represented as a passing test run.

Subsequent delivery (Fase 7, 2026-08-30) made CI the reproducible production
gate: full-suite pytest 3.11/3.12, branch coverage, Ruff, Bandit, dependency
audit, Alembic fresh install + upgrade, merge-gate, Bubblewrap, SDK proxy
matrix, and E2E on the dedicated integration runner, all evaluated into a
single release candidate by `ci/release_candidate.py`. The 14 legacy
environment failures are governed by the controlled platform-skip manifest
(`ci/manifests/platform_skips.json`) rather than blanket skipping.

Fase 8 (2026-08-30) added operational runbooks (`docs/RUNBOOKS.md`),
staging certification / reconciliation tooling (`ci/staging/`), and the
deploy-failure fire drill (`scripts/fire_drill.sh`).
