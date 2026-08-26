"""Point-in-time SQLite schema and data snapshots."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemaSnapshot:
    """Self-contained SQLite backup with integrity metadata."""
    database_path: str
    backup_path: str
    schema_sql: str
    checksum: str

    @classmethod
    def create(cls, database_path: str | Path, backup_path: str | Path) -> "SchemaSnapshot":
        """Create a consistent SQLite backup and capture its schema."""
        source = sqlite3.connect(str(database_path))
        try:
            integrity = source.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("source database failed integrity_check")
            schema = "\n".join(row[0] for row in source.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"))
            destination = sqlite3.connect(str(backup_path))
            try:
                source.backup(destination)
                destination.commit()
                payload = Path(backup_path).read_bytes()
            finally:
                destination.close()
            return cls(str(database_path), str(backup_path), schema, hashlib.sha256(payload).hexdigest())
        finally:
            source.close()

    def verify(self) -> bool:
        """Verify backup checksum and SQLite integrity."""
        path = Path(self.backup_path)
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != self.checksum:
            return False
        connection = sqlite3.connect(self.backup_path)
        try:
            return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            connection.close()

    def restore(self, target_path: str | Path) -> None:
        """Restore the snapshot to a target database atomically via SQLite backup."""
        if not self.verify():
            raise RuntimeError("snapshot verification failed")
        target = sqlite3.connect(str(target_path))
        source = sqlite3.connect(self.backup_path)
        try:
            source.backup(target)
            target.commit()
        finally:
            source.close()
            target.close()
