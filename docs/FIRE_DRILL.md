# Fase 8 — Deploy-failure fire drill

The fire drill turns the Fase 8 requirement *"deploy-fiasko-fire drill"* into
a runnable, quarterly exercise. It is the operational proof that:

- unknown PR / image / deployment status is **reconciled deterministically**
  (`R-11`),
- an uncertified digest deployed to staging is **detected** and
  **ROLLBACK_REQUIRED** (`R-10`),
- staging can **roll back to a known digest** (`R-10`),
- restore-from-backup is exercised on a fresh target (`R-05`).

## Run the drill

```bash
bash scripts/fire_drill.sh
```

The script is self-contained: it seeds a throwaway certification ledger
(`mktemp`), classifies an unknown deployment, forces a rollback, and verifies
the post-rollback state. It requires only Python + the `ci` package
(`PYTHONPATH=.` is exported by the script).

Optional environment:

| Variable | Default | Meaning |
|---|---|---|
| `DOR_REPO` | `smoeberg/kodegenerator` | repository under drill |
| `DOR_IMAGE` | `ghcr.io/smoeberg/kodegenerator` | image under drill |
| `DOR_LEDGER` | temp file | certification ledger to use/seed |
| `DOR_CERT_DIGEST` | `sha256:firedrill-certified-abcdef` | the known digest |
| `DOR_BAD_DIGEST` | `sha256:firedrill-uncertified-123456` | the compromised digest |
| `DOR_GATE_RUN` | `firedrill-run-<ts>` | gate run id recorded with certification |
| `DOR_SKIP_RESTORE` | `0` | set to `1` to skip the pg_restore smoke check |

## Success criteria

The drill is **green** only when every step ends in `OK` or an approved,
recorded rollback, and it prints:

```
PASS: 6  FAIL: 0
```

## Drill steps (map to runbooks)

| Step | Checks | Runbook |
|---|---|---|
| 0 | seed ledger with a known digest | `R-09` |
| 1 | unknown status classified `PENDING` | `R-11` |
| 2 | uncertified deployed digest -> `ROLLBACK_REQUIRED` | `R-11` |
| 3 | rollback target resolves to the certified digest | `R-10` |
| 4 | post-rollback staging reconciled `OK` | `R-10`/`R-11` |
| 5 | restore-from-backup smoke check | `R-05` |

A quarterly drill must additionally cover a **real** restore from backup
(`R-05`) and a **registry vendor switch** (`R-07`) on the integration
runner with the certification suite
(`tests/pipeline/test_release_executor.py`) — those steps require DB tooling
and a Docker registry, so they are host-dependent, but the reconciliation
core of the drill runs anywhere.

## Recording

Every drill must be recorded in the ops log with: timestamp, operator,
ledger seed, classifications observed, rollback target used, and the final
PASS/FAIL counts.
