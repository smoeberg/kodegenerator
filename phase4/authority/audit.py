"""Authority decision audit port (Programmer 1 — pure AI-3 boundary).

``AuthorityEngine`` always keeps an in-process trail via ``audit_trail()``.
An optional ``AuthorityAuditSink`` receives the same immutable decisions for
export (metrics, structured logs, durable store) without coupling the engine
to infrastructure.

Sink implementations must not grant authority, execute work, or mutate the
decision object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, Sequence, Tuple

from .models import AuthorityDecision


class AuthorityAuditSink(Protocol):
    """Receives every authority decision (ALLOW and DENY)."""

    def record(self, decision: AuthorityDecision) -> None:
        """Record one immutable decision. Must be safe to call concurrently."""


class NullAuthorityAuditSink:
    """Default no-op sink — evaluation does not depend on external I/O."""

    def record(self, decision: AuthorityDecision) -> None:
        return None


@dataclass
class RecordingAuthorityAuditSink:
    """In-memory sink for tests and process-local export."""

    _decisions: list[AuthorityDecision] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock)

    def record(self, decision: AuthorityDecision) -> None:
        with self._lock:
            self._decisions.append(decision)

    def decisions(self) -> Tuple[AuthorityDecision, ...]:
        with self._lock:
            return tuple(self._decisions)

    def clear(self) -> None:
        with self._lock:
            self._decisions.clear()


def composite_audit_sink(*sinks: AuthorityAuditSink) -> AuthorityAuditSink:
    """Fan-out to multiple sinks; first failure aborts remaining sinks."""

    class _Composite:
        def record(self, decision: AuthorityDecision) -> None:
            for sink in sinks:
                sink.record(decision)

    return _Composite()


def _as_sink(sink: AuthorityAuditSink | None) -> AuthorityAuditSink:
    return NullAuthorityAuditSink() if sink is None else sink
