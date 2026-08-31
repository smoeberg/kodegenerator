# Redmine Error Ticketing

DOR can open tracking issues on a self-hosted [Redmine](https://www.redmine.org/)
instance when internal error paths fire. The integration is **optional and
non-blocking**: every entry point degrades gracefully when Redmine is not
configured, reachable, or returns errors.

## Configuration

All settings come from the environment (see `.env.example`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `REDMINE_URL` | yes | – | Base URL, e.g. `https://redmine.example.com` |
| `REDMINE_API_KEY` | yes | – | Redmine REST API key |
| `REDMINE_PROJECT_ID` | no | `dor` | Project identifier for issues |
| `REDMINE_ISSUE_TRACKER_ID` | no | `1` | Tracker id for bug tickets |
| `REDMINE_MAX_ISSUES_PER_RUN` | no | `5` | Rate cap per process run |
| `REDMINE_DEDUP_WINDOW_DAYS` | no | `7` | Dedup window for identical errors |

When `REDMINE_URL` or `REDMINE_API_KEY` are missing, the integration is
disabled and all calls become no-ops.

## What gets ticketed

1. **Self-healing exhaustion** — when the
   `SelfHealingSynthesisLoop` reaches `max_attempts` without convergence, a
   ticket is opened with the module name, error text, attempt count and the
   architectural context.
2. **Generation failures** — `generation/redmine_reporting.py` wraps the
   scaffold generation entrypoint and reports unrecoverable failures.

## Behavior

- **Non-blocking**: ticketing never changes the caller's result. Failures in
  the ticketing layer itself are swallowed and surfaced only as a note on the
  existing result object.
- **Deduplication** (`use_deduplication=True`): identical errors are only
  ticketed once per dedup window, keyed by `(kind, module, fingerprint of
  error text)`.
- **Rate cap**: at most `REDMINE_MAX_ISSUES_PER_RUN` issues are opened per
  process run.
- The HTTP transport (`services/redmine_api.py`) uses timeouts and retries
  with backoff, and never raises into the caller.

## Modules

| Module | Responsibility |
|---|---|
| `services/redmine_contracts.py` | Data contracts (`RedmineConfig`, `RedmineIssue`, `RedmineTicketResult`) and env parsing |
| `services/redmine_api.py` | Thin HTTP transport over the Redmine REST API (`issues.json`) |
| `services/redmine_error_ticketing.py` | Orchestration: dedup, rate cap, result mapping |
| `generation/redmine_reporting.py` | Generation-scope wrapper |
| `services/self_healing_synthesis.py` | Hook in `SelfHealingSynthesisLoop` (`_report_exhaustion`, `with_redmine_from_env`) |

## Tests

```
pytest tests/services/test_redmine_contracts.py tests/services/test_redmine_error_ticketing.py
```
