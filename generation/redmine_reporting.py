"""Non-blocking Redmine error reporting for the generation pipeline.

The generation contract must never depend on ticketing availability, so
this module exposes a thin helper that swallows all Redmine errors while
still returning the outcome for observability. The heavy lifting lives in
:mod:`services.redmine_error_ticketing`.
"""

from __future__ import annotations

from typing import Any

from services.redmine_contracts import RedmineErrorKind, RedmineTicketResult
from services.redmine_error_ticketing import RedmineErrorTickerService


def report_generation_failure(
    ticker: RedmineErrorTickerService | None,
    *,
    module: str,
    error: str,
    context: dict[str, Any] | None = None,
) -> RedmineTicketResult:
    """Best-effort report of a generation failure; never raises.

    Returns a non-ok :class:`RedmineTicketResult` (``error="not-configured"``)
    when no ticker is wired, so callers can log without branching.
    """
    if ticker is None:
        return RedmineTicketResult(
            kind=RedmineErrorKind.GENERATION, error="not-configured"
        )
    try:
        return ticker.report_verification_failure(
            module=module,
            error=error,
            context=context or {},
            kind=RedmineErrorKind.GENERATION,
        )
    except Exception as exc:  # noqa: BLE001 - pragma: no cover - defensive only
        return RedmineTicketResult(
            kind=RedmineErrorKind.GENERATION, error=f"ticketing-error: {exc}"
        )
