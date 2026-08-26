"""Cryptographically sealed swarm state snapshots.

The snapshot format is deliberately adapter based: callers provide named state
providers, so SQLite queues, ledgers, counters and worker registries can be
captured without coupling this module to their concrete implementations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class SnapshotMetadata:
    """Metadata describing a sealed snapshot."""
    snapshot_id: str
    created_at: str
    manifest_sha256: str
    signature: str | None
    path: str


class StateSnapshot:
    """Create, validate, drill and restore immutable ZIP snapshots."""

    MANIFEST = "manifest.json"
    SIGNATURE = "manifest.sig"

    def __init__(self, root: str | Path, signing_key: bytes | None = None) -> None:
        """Initialize snapshot storage and optional HMAC signing key."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.signing_key = signing_key

    def create(self, states: Mapping[str, Any], snapshot_id: str | None = None) -> SnapshotMetadata:
        """Serialize named state providers into a sealed ZIP archive."""
        sid = snapshot_id or str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        payloads: dict[str, bytes] = {}
        for name, value in states.items():
            if not name or "/" in name or "\\" in name:
                raise ValueError("state names must be simple path-safe names")
            payloads[f"state/{name}.json"] = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        manifest = {
            "version": 1,
            "snapshot_id": sid,
            "created_at": created,
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())},
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        signature = self._sign(manifest_bytes)
        archive = self.root / f"{sid}.zip"
        fd, temp_name = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for name, data in sorted(payloads.items()): zf.writestr(name, data)
                zf.writestr(self.MANIFEST, manifest_bytes)
                if signature is not None: zf.writestr(self.SIGNATURE, signature)
            os.replace(temp_name, archive)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)
        return SnapshotMetadata(sid, created, manifest_hash, signature, str(archive))

    def validate(self, snapshot_id: str) -> SnapshotMetadata:
        """Validate ZIP structure, hashes and optional signature before use."""
        archive = self._path(snapshot_id)
        with zipfile.ZipFile(archive, "r") as zf:
            manifest_bytes = zf.read(self.MANIFEST)
            manifest = json.loads(manifest_bytes)
            if manifest.get("snapshot_id") != snapshot_id: raise ValueError("snapshot id mismatch")
            expected = manifest.get("files", {})
            for name, digest in expected.items():
                actual = hashlib.sha256(zf.read(name)).hexdigest()
                if not hmac.compare_digest(actual, digest): raise ValueError(f"integrity failure: {name}")
            signature = zf.read(self.SIGNATURE).decode() if self.SIGNATURE in zf.namelist() else None
            if self.signing_key is not None:
                if signature is None or not hmac.compare_digest(signature, self._sign(manifest_bytes) or ""):
                    raise ValueError("signature validation failed")
        return SnapshotMetadata(snapshot_id, str(manifest["created_at"]), hashlib.sha256(manifest_bytes).hexdigest(), signature, str(archive))

    def read_states(self, snapshot_id: str) -> dict[str, Any]:
        """Validate and return snapshot state without activating it."""
        self.validate(snapshot_id)
        with zipfile.ZipFile(self._path(snapshot_id), "r") as zf:
            return {name.removeprefix("state/").removesuffix(".json"): json.loads(zf.read(name)) for name in zf.namelist() if name.startswith("state/")}

    def drill(self, snapshot_id: str) -> SnapshotMetadata:
        """Validate a snapshot without modifying live state."""
        return self.validate(snapshot_id)

    def restore(self, snapshot_id: str, target: str | Path) -> dict[str, Any]:
        """Atomically replace a target state directory after validation."""
        states = self.read_states(snapshot_id)
        target_path = Path(target)
        parent = target_path.parent
        staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".restore-{snapshot_id}-"))
        try:
            for name, value in states.items():
                (staging / f"{name}.json").write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            backup = parent / f".{target_path.name}.backup-{uuid.uuid4()}"
            if target_path.exists(): os.replace(target_path, backup)
            os.replace(staging, target_path)
            if backup.exists():
                import shutil
                shutil.rmtree(backup)
            return states
        except Exception:
            if staging.exists():
                import shutil
                shutil.rmtree(staging)
            raise

    def _path(self, snapshot_id: str) -> Path:
        if not snapshot_id or Path(snapshot_id).name != snapshot_id: raise ValueError("invalid snapshot id")
        path = self.root / f"{snapshot_id}.zip"
        if not path.is_file(): raise FileNotFoundError(snapshot_id)
        return path

    def _sign(self, data: bytes) -> str | None:
        return hmac.new(self.signing_key, data, hashlib.sha256).hexdigest() if self.signing_key is not None else None
