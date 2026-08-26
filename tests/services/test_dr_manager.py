"""Deep tests for disaster-recovery snapshot management."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services.dr_manager import DRManager, RetentionPolicy
from services.state_snapshot import StateSnapshot


def test_snapshot_round_trip_and_atomic_restore(tmp_path: Path) -> None:
    """A sealed snapshot restores the complete named state."""
    store = tmp_path / "snapshots"
    target = tmp_path / "live"
    snapshot = StateSnapshot(store, signing_key=b"enterprise-key")
    manager = DRManager(snapshot)
    manager.register_state("queue", lambda: {"pending": ["t1", "t2"]})
    manager.register_state("workers", lambda: {"w1": "READY"})
    metadata = manager.snapshot_now()
    target.mkdir(); (target / "stale.json").write_text("stale")
    restored = manager.restore(metadata.snapshot_id, target)
    assert restored["queue"]["pending"] == ["t1", "t2"]
    assert restored["workers"]["w1"] == "READY"
    assert not (target / "stale.json").exists()


def test_integrity_tampering_is_rejected(tmp_path: Path) -> None:
    """Changing a payload after sealing prevents restore/drill."""
    snapshot = StateSnapshot(tmp_path, signing_key=b"key")
    metadata = snapshot.create({"ledger": {"entries": [1]}})
    import zipfile
    path = Path(metadata.path)
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("state/ledger.json", json.dumps({"entries": [999]}))
    with pytest.raises(ValueError, match="integrity failure"):
        snapshot.drill(metadata.snapshot_id)


def test_drill_never_activates_state(tmp_path: Path) -> None:
    """A drill validates the archive while leaving the target untouched."""
    snapshot = StateSnapshot(tmp_path, signing_key=b"key")
    metadata = snapshot.create({"queue": {"status": "safe"}})
    target = tmp_path / "live"; target.mkdir(); marker = target / "marker"; marker.write_text("live")
    result = DRManager(snapshot).drill(metadata.snapshot_id)
    assert result.snapshot_id == metadata.snapshot_id
    assert marker.read_text() == "live"


def test_retention_limits_snapshot_count(tmp_path: Path) -> None:
    """Retention removes the oldest archives beyond the configured count."""
    snapshot = StateSnapshot(tmp_path)
    manager = DRManager(snapshot, retention=RetentionPolicy(max_snapshots=2, max_age_hours=100))
    for _ in range(3):
        manager.snapshot_now(); time.sleep(0.01)
    assert len(list(tmp_path.glob("*.zip"))) == 2


def test_scheduler_can_start_and_stop(tmp_path: Path) -> None:
    """The scheduler performs cycles and shuts down without leaking a thread."""
    snapshot = StateSnapshot(tmp_path)
    calls: list[int] = []
    manager = DRManager(snapshot, interval_seconds=1)
    manager.register_state("counter", lambda: calls.append(1) or {"calls": len(calls)})
    manager.start(); time.sleep(1.15); manager.stop()
    assert calls
    assert manager._thread is None
