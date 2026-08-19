"""Audit and observability primitives for Phase 6 execution."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class ExecutionAuditEvent:
    """Minimal, structured audit record for one sandbox lifecycle transition."""

    event_type: str
    execution_id: str
    adapter_id: str
    outcome: str
    timestamp: str
    detail: str | None = None
    error_code: str | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if not self.event_type.strip() or not self.execution_id.strip() or not self.adapter_id.strip():
            raise ValueError("audit identity fields must be non-empty")
        if len(self.execution_id) > 256 or len(self.adapter_id) > 128 or len(self.outcome) > 64:
            raise ValueError("audit fields exceed configured bounds")
        if self.detail is not None and len(self.detail) > 64:
            raise ValueError("audit detail exceeds configured bounds")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class AuditSink(Protocol):
    """Destination for trusted, structured execution audit events."""

    def emit(self, event: ExecutionAuditEvent) -> None: ...


class StructuredAuditLogger:
    """Emit JSON audit records without command, environment, or secret data."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("dor.phase6.audit")

    def emit(self, event: ExecutionAuditEvent) -> None:
        payload = json.dumps(event.as_dict(), sort_keys=True, separators=(",", ":"))
        self._logger.info("phase6_execution_audit %s", payload)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class NullAuditSink:
    """Explicit no-op sink for callers that do not need persistence."""

    def emit(self, event: ExecutionAuditEvent) -> None:
        return None
