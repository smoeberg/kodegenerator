"""Non-blocking Redmine error reporting for the generation pipeline.

The generation contract must never depend on ticketing availability, so
this module exposes a thin helper that swallows all Redmine errors while
still returning the outcome for observability. The heavy lifting lives in
:mod:`services.redmine_error_ticketing`.

Monitoring: :class:`RedmineReporterMetrics` keeps per-run counters that
callers can expose as logs/metrics; ticketing is best-effort and never
raises.
"""

from __future__ import annotations

import functools
import time
from collections import Counter
from collections.abc import Callable
from typing import Any, TypeVar

from services.redmine_contracts import RedmineErrorKind, RedmineTicketResult
from services.redmine_error_ticketing import RedmineErrorTickerService

T = TypeVar("T")


class RedmineReporterMetrics:
    """Lightweight counters for observability of the reporter.

    The counters are updated by :func:`report_generation_failure`; they
    are process-local and thread-safe for the common single-threaded use.
    """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.last_error: str | None = None
        self.total_duration_seconds: float = 0.0
        self._calls = 0

    def record(self, result: RedmineTicketResult, duration: float) -> None:
        """Record one reporting attempt."""
        self._calls += 1
        self.total_duration_seconds += duration
        if result.ok:
            if result.deduplicated:
                self.counts["deduplicated"] += 1
            else:
                self.counts["sent"] += 1
        else:
            self.counts["failed"] += 1
            self.last_error = result.error

    @property
    def calls(self) -> int:
        return self._calls

    def snapshot(self) -> dict[str, Any]:
        """Return a plain-dict snapshot for logging/metrics export."""
        return {
            "calls": self._calls,
            "sent": self.counts["sent"],
            "deduplicated": self.counts["deduplicated"],
            "failed": self.counts["failed"],
            "last_error": self.last_error,
            "total_duration_seconds": round(self.total_duration_seconds, 4),
        }


def report_generation_failure(
    ticker: RedmineErrorTickerService | None,
    *,
    module: str,
    error: str,
    context: dict[str, Any] | None = None,
    metrics: RedmineReporterMetrics | None = None,
) -> RedmineTicketResult:
    """Best-effort report of a generation failure; never raises.

    Returns a non-ok :class:`RedmineTicketResult` (``error="not-configured"``)
    when no ticker is wired, so callers can log without branching.
    """
    start = time.monotonic()
    if ticker is None:
        result = RedmineTicketResult(
            kind=RedmineErrorKind.GENERATION, error="not-configured"
        )
    else:
        try:
            result = ticker.report_verification_failure(
                module=module,
                error=error,
                context=context or {},
                kind=RedmineErrorKind.GENERATION,
            )
        except Exception as exc:  # noqa: BLE001 - pragma: no cover - defensive only
            result = RedmineTicketResult(
                kind=RedmineErrorKind.GENERATION, error=f"ticketing-error: {exc}"
            )
    if metrics is not None:
        metrics.record(result, time.monotonic() - start)
    return result


def redmine_error_reporter(
    ticker: RedmineErrorTickerService | None,
    *,
    module: str = "generation",
    metrics: RedmineReporterMetrics | None = None,
):
    """Decorator: wrap a generation callable so failures are ticketed.

    The wrapper never changes the original result — successful calls pass
    through untouched, and exceptions are re-raised after a best-effort
    Redmine report. This keeps the generation contract independent of
    ticketing availability.
    """

    def decorate(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                report_generation_failure(
                    ticker,
                    module=module,
                    error=str(exc),
                    context={"function": fn.__name__, "args": args, "kwargs": kwargs},
                    metrics=metrics,
                )
                raise

        return wrapper

    return decorate
