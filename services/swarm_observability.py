"""Tamper-evident audit logging and derived swarm metrics."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


class SwarmEventType(str, Enum):
    PROJECT_STARTED = "PROJECT_STARTED"
    TASK_CLAIMED = "TASK_CLAIMED"
    HEARTBEAT = "HEARTBEAT"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    RECLAIMED = "RECLAIMED"
    MERGE_APPROVED = "MERGE_APPROVED"
    MERGE_BLOCKED = "MERGE_BLOCKED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"


@dataclass(frozen=True)
class SwarmAuditEvent:
    timestamp: str
    event_type: str
    worker_id: str | None
    task_id: str | None
    project_id: str | None
    payload: dict[str, Any]
    event_hash: str


class SwarmAuditLog:
    """Append-only SQLite audit log with a SHA-256 hash chain."""
    GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS swarm_audit_events ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
            "event_type TEXT NOT NULL, worker_id TEXT, task_id TEXT, project_id TEXT, "
            "payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE)"
        )
        self._db.commit()

    def append(self, event_type: SwarmEventType | str, *, worker_id: str | None = None,
               task_id: str | None = None, project_id: str | None = None,
               payload: Mapping[str, Any] | None = None,
               timestamp: datetime | None = None) -> SwarmAuditEvent:
        name = event_type.value if isinstance(event_type, SwarmEventType) else str(event_type)
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        stamp = now.astimezone(timezone.utc).isoformat()
        data = dict(payload or {})
        content = {"timestamp": stamp, "event_type": name, "worker_id": worker_id,
                   "task_id": task_id, "project_id": project_id, "payload": data}
        with self._lock:
            row = self._db.execute(
                "SELECT event_hash FROM swarm_audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous = row["event_hash"] if row else self.GENESIS_HASH
            event_hash = hashlib.sha256(
                (previous + _canonical(content)).encode("utf-8")
            ).hexdigest()
            self._db.execute(
                "INSERT INTO swarm_audit_events "
                "(timestamp,event_type,worker_id,task_id,project_id,payload,previous_hash,event_hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (stamp, name, worker_id, task_id, project_id, _canonical(data), previous, event_hash),
            )
            self._db.commit()
        return SwarmAuditEvent(stamp, name, worker_id, task_id, project_id, data, event_hash)

    def events(self) -> list[SwarmAuditEvent]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM swarm_audit_events ORDER BY sequence").fetchall()
        return [SwarmAuditEvent(r["timestamp"], r["event_type"], r["worker_id"],
                                r["task_id"], r["project_id"], json.loads(r["payload"]),
                                r["event_hash"]) for r in rows]

    def verify_chain(self) -> bool:
        with self._lock:
            rows = self._db.execute("SELECT * FROM swarm_audit_events ORDER BY sequence").fetchall()
        previous = self.GENESIS_HASH
        for row in rows:
            content = {"timestamp": row["timestamp"], "event_type": row["event_type"],
                       "worker_id": row["worker_id"], "task_id": row["task_id"],
                       "project_id": row["project_id"], "payload": json.loads(row["payload"])}
            expected = hashlib.sha256((previous + _canonical(content)).encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous or row["event_hash"] != expected:
                return False
            previous = row["event_hash"]
        return True

    def close(self) -> None:
        with self._lock:
            self._db.close()


@dataclass(frozen=True)
class SwarmMetricsSnapshot:
    tasks_claimed: int
    tasks_completed: int
    tasks_failed: int
    avg_claim_duration: float
    merge_latency: float

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class SwarmMetrics:
    def __init__(self, audit_log: SwarmAuditLog) -> None:
        self.audit_log = audit_log

    def snapshot(self) -> SwarmMetricsSnapshot:
        events = self.audit_log.events()
        claims: dict[str, datetime] = {}
        durations: list[float] = []
        merges: list[float] = []
        for event in events:
            when = _parse(event.timestamp)
            if event.event_type == SwarmEventType.TASK_CLAIMED.value and event.task_id:
                claims[event.task_id] = when
            elif event.event_type in (SwarmEventType.TASK_COMPLETED.value, SwarmEventType.TASK_FAILED.value) and event.task_id:
                start = claims.pop(event.task_id, None)
                if start:
                    durations.append(max(0.0, (when - start).total_seconds()))
            elif event.event_type in (SwarmEventType.MERGE_APPROVED.value, SwarmEventType.MERGE_BLOCKED.value):
                started = event.payload.get("merge_started_at")
                if started:
                    merges.append(max(0.0, (when - _parse(str(started))).total_seconds()))
        return SwarmMetricsSnapshot(
            tasks_claimed=sum(e.event_type == SwarmEventType.TASK_CLAIMED.value for e in events),
            tasks_completed=sum(e.event_type == SwarmEventType.TASK_COMPLETED.value for e in events),
            tasks_failed=sum(e.event_type == SwarmEventType.TASK_FAILED.value for e in events),
            avg_claim_duration=sum(durations) / len(durations) if durations else 0.0,
            merge_latency=sum(merges) / len(merges) if merges else 0.0,
        )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
