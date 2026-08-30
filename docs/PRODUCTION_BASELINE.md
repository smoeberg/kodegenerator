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
