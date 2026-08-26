"""Enterprise append-only audit log with hash chaining and SIEM export.

Events are hash-chained (SHA-256) so tampering breaks the chain. Exporters
emit JSON-lines, Syslog RFC5424, and CEF. Signature validation failures on
import/replay result in silent-drop of the bad record (fail-closed for SIEM).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"
    ERROR = "error"


@dataclass(frozen=True)
class AuditEvent:
    """Single immutable audit record."""

    event_id: str
    actor_id: str
    action: str
    resource: str
    outcome: AuditOutcome
    timestamp: datetime
    tenant_id: str = ""
    project_id: str = ""
    detail: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    event_hash: str = ""

    def canonical_payload(self) -> str:
        payload = {
            "event_id": self.event_id,
            "actor_id": self.actor_id,
            "action": self.action,
            "resource": self.resource,
            "outcome": self.outcome.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "detail": self.detail,
            "metadata": dict(self.metadata),
            "prev_hash": self.prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_payload().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "actor_id": self.actor_id,
            "action": self.action,
            "resource": self.resource,
            "outcome": self.outcome.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "detail": self.detail,
            "metadata": dict(self.metadata),
            "prev_hash": self.prev_hash,
            "event_hash": self.event_hash,
        }


class EnterpriseAuditLog:
    """Thread-safe append-only hash-chained audit log."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []
        self._last_hash = GENESIS_HASH
        self._seq = 0

    def append(
        self,
        *,
        actor_id: str,
        action: str,
        resource: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        tenant_id: str = "",
        project_id: str = "",
        detail: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> AuditEvent:
        if isinstance(outcome, str):
            outcome = AuditOutcome(outcome)
        with self._lock:
            self._seq += 1
            event_id = f"ae_{self._seq:08d}"
            provisional = AuditEvent(
                event_id=event_id,
                actor_id=actor_id,
                action=action,
                resource=resource,
                outcome=outcome,
                timestamp=timestamp or _utcnow(),
                tenant_id=tenant_id,
                project_id=project_id,
                detail=detail,
                metadata=dict(metadata or {}),
                prev_hash=self._last_hash,
                event_hash="",
            )
            event_hash = provisional.compute_hash()
            sealed = AuditEvent(
                event_id=provisional.event_id,
                actor_id=provisional.actor_id,
                action=provisional.action,
                resource=provisional.resource,
                outcome=provisional.outcome,
                timestamp=provisional.timestamp,
                tenant_id=provisional.tenant_id,
                project_id=provisional.project_id,
                detail=provisional.detail,
                metadata=provisional.metadata,
                prev_hash=provisional.prev_hash,
                event_hash=event_hash,
            )
            self._events.append(sealed)
            self._last_hash = event_hash
            return sealed

    def events(
        self,
        *,
        tenant_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> tuple[AuditEvent, ...]:
        with self._lock:
            items = list(self._events)
        if tenant_id is not None:
            items = [e for e in items if e.tenant_id == tenant_id]
        if actor_id is not None:
            items = [e for e in items if e.actor_id == actor_id]
        return tuple(items)

    def verify_chain(self) -> bool:
        with self._lock:
            prev = GENESIS_HASH
            for event in self._events:
                if event.prev_hash != prev:
                    return False
                if event.compute_hash() != event.event_hash:
                    return False
                prev = event.event_hash
        return True

    @property
    def tip_hash(self) -> str:
        with self._lock:
            return self._last_hash


def export_jsonl(events: Sequence[AuditEvent], path: Path | str) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            if not _valid_event(event):
                logger.warning("silent-drop invalid audit event %s", event.event_id)
                continue
            handle.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")
            count += 1
    return count


def format_syslog_rfc5424(event: AuditEvent, *, app_name: str = "kodegen") -> str:
    ts = event.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    msg = (
        f"actor={event.actor_id} action={event.action} resource={event.resource} "
        f"outcome={event.outcome.value} tenant={event.tenant_id} "
        f"project={event.project_id} detail={event.detail}"
    )
    return f"1 {ts} localhost {app_name} - {event.event_id} - {msg}"


def format_cef(
    event: AuditEvent,
    *,
    device_vendor: str = "DOR",
    device_product: str = "kodegen",
) -> str:
    severity = {
        AuditOutcome.SUCCESS: 3,
        AuditOutcome.DENIED: 7,
        AuditOutcome.FAILURE: 6,
        AuditOutcome.ERROR: 8,
    }.get(event.outcome, 5)
    extension = (
        f"act={_cef_escape(event.action)} "
        f"suser={_cef_escape(event.actor_id)} "
        f"cs1={_cef_escape(event.tenant_id)} "
        f"cs1Label=tenant "
        f"cs2={_cef_escape(event.project_id)} "
        f"cs2Label=project "
        f"msg={_cef_escape(event.detail)} "
        f"outcome={event.outcome.value} "
        f"cs3={_cef_escape(event.event_hash)} "
        f"cs3Label=eventHash"
    )
    return (
        f"CEF:0|{device_vendor}|{device_product}|1.0|{event.action}|"
        f"{_cef_escape(event.resource)}|{severity}|{extension}"
    )


def export_syslog(
    events: Sequence[AuditEvent],
    path: Path | str,
    *,
    fmt: str = "rfc5424",
) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = format_cef if fmt == "cef" else format_syslog_rfc5424
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            if not _valid_event(event):
                logger.warning("silent-drop invalid audit event %s", event.event_id)
                continue
            handle.write(formatter(event) + "\n")
            count += 1
    return count


def _valid_event(event: AuditEvent) -> bool:
    try:
        return event.compute_hash() == event.event_hash and bool(event.event_hash)
    except Exception:  # noqa: BLE001
        return False


def _cef_escape(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace("\n", " ")
        .replace("|", "\\|")
    )


class AuditingRBACGuard:
    """RBACGuard wrapper that records allow/deny decisions in the audit log."""

    def __init__(self, policy: Any, audit: EnterpriseAuditLog) -> None:
        from services.rbac import RBACGuard

        self._guard = RBACGuard(policy)
        self.audit = audit

    def enforce(self, principal: Any, permission: Any, **kwargs: Any) -> Any:
        from services.rbac import AccessDenied

        tenant_id = kwargs.get("tenant_id") or getattr(principal, "tenant_id", "") or ""
        project_id = kwargs.get("project_id") or getattr(principal, "project_id", "") or ""
        try:
            result = self._guard.enforce(principal, permission, **kwargs)
            self.audit.append(
                actor_id=principal.actor_id,
                action=f"rbac.allow.{permission.value}",
                resource=f"tenant:{tenant_id}/project:{project_id}",
                outcome=AuditOutcome.SUCCESS,
                tenant_id=str(tenant_id or ""),
                project_id=str(project_id or ""),
            )
            return result
        except AccessDenied as exc:
            self.audit.append(
                actor_id=principal.actor_id,
                action=f"rbac.deny.{permission.value}",
                resource=f"tenant:{tenant_id}/project:{project_id}",
                outcome=AuditOutcome.DENIED,
                tenant_id=str(tenant_id or ""),
                project_id=str(project_id or ""),
                detail=str(exc),
            )
            raise
