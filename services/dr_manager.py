"""Disaster-recovery snapshot scheduling and retention management."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable, Mapping

from .state_snapshot import SnapshotMetadata, StateSnapshot


@dataclass(frozen=True)
class RetentionPolicy:
    """Snapshot retention limits."""
    max_snapshots: int = 96
    max_age_hours: int = 24 * 30


class DRManager:
    """Coordinate periodic, retained and restorable swarm snapshots."""

    def __init__(self, snapshot: StateSnapshot, *, interval_seconds: int = 900, retention: RetentionPolicy | None = None) -> None:
        """Initialize a manager with a 15-minute default cycle."""
        if interval_seconds <= 0: raise ValueError("interval_seconds must be positive")
        if retention is not None and (retention.max_snapshots <= 0 or retention.max_age_hours <= 0): raise ValueError("invalid retention policy")
        self.snapshot = snapshot
        self.interval_seconds = interval_seconds
        self.retention = retention or RetentionPolicy()
        self._providers: dict[str, Callable[[], Any]] = {}
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None

    def register_state(self, name: str, provider: Callable[[], Any]) -> None:
        """Register a named state provider captured by each cycle."""
        if not name or "/" in name or "\\" in name: raise ValueError("invalid state name")
        with self._lock: self._providers[name] = provider

    def snapshot_now(self) -> SnapshotMetadata:
        """Capture all currently registered state providers and enforce retention."""
        with self._lock: states = {name: provider() for name, provider in self._providers.items()}
        metadata = self.snapshot.create(states)
        self.enforce_retention()
        return metadata

    def restore(self, snapshot_id: str, target: str | Path) -> dict[str, Any]:
        """Validate and atomically restore a snapshot into the target directory."""
        return self.snapshot.restore(snapshot_id, target)

    def drill(self, snapshot_id: str) -> SnapshotMetadata:
        """Run an integrity-only restore drill without activation."""
        return self.snapshot.drill(snapshot_id)

    def enforce_retention(self) -> None:
        """Delete snapshots exceeding count or age limits."""
        now = datetime.now(timezone.utc)
        files = sorted(self.snapshot.root.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for index, path in enumerate(files):
            too_many = index >= self.retention.max_snapshots
            too_old = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < now - timedelta(hours=self.retention.max_age_hours)
            if too_many or too_old: path.unlink(missing_ok=True)

    def start(self) -> None:
        """Start the background snapshot scheduler idempotently."""
        with self._lock:
            if self._thread and self._thread.is_alive(): return
            self._stop.clear(); self._thread = Thread(target=self._run, name="dor-dr-snapshot", daemon=True); self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler and wait briefly for termination."""
        self._stop.set()
        thread = self._thread
        if thread: thread.join(timeout=self.interval_seconds + 1)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try: self.snapshot_now()
            except Exception:
                # Snapshot failures must not kill the scheduler; callers can observe filesystem/audit telemetry.
                continue
