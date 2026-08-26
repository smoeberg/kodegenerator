"""Transactional SQLite migration planning, replay and rollback helpers."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .schema_snapshot import SchemaSnapshot


STEPS = ("prepare", "validate", "apply", "verify", "finalize")


@dataclass(frozen=True)
class ReplayWrite:
    """Deterministic write operation captured for replay."""
    sql: str
    parameters: tuple[object, ...] = ()


@dataclass(frozen=True)
class MigrationPlan:
    """Immutable migration plan."""
    version: str
    statements: tuple[str, ...]
    rollback_statements: tuple[str, ...]


class MigrationEngine:
    """Runs SQLite migrations with backups, validation and deterministic replay."""

    def __init__(self, database_path: str | Path, backup_dir: str | Path) -> None:
        self.database_path = str(database_path)
        self.backup_dir = Path(backup_dir)
        self._replay: list[ReplayWrite] = []
        self._capturing = False

    def prepare(self, statements: Iterable[str], version: str) -> MigrationPlan:
        """Build a migration plan and generate conservative rollback SQL."""
        normalized = tuple(statement.strip() for statement in statements if statement.strip())
        rollback = tuple(self._rollback_for(statement) for statement in reversed(normalized) if self._rollback_for(statement))
        return MigrationPlan(version, normalized, rollback)

    def execute(self, plan: MigrationPlan, validate: Callable[[sqlite3.Connection], bool] | None = None) -> SchemaSnapshot:
        """Execute prepare/validate/apply/verify/finalize with a backup before each step."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        snapshots: list[SchemaSnapshot] = []
        connection = sqlite3.connect(self.database_path)
        try:
            for step in STEPS:
                snapshot = SchemaSnapshot.create(self.database_path, self.backup_dir / f"{plan.version}-{step}.sqlite")
                snapshots.append(snapshot)
                if step == "validate":
                    if validate is not None and not validate(connection):
                        raise RuntimeError("migration validation failed")
                elif step == "apply":
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in plan.statements:
                            connection.execute(statement)
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
                elif step == "verify":
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                    if result != ("ok",):
                        raise RuntimeError("post-migration integrity check failed")
                elif step == "finalize":
                    connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
            return snapshots[-1]
        except Exception:
            if snapshots:
                snapshots[0].restore(self.database_path)
            raise
        finally:
            connection.close()

    def start_replay(self) -> None:
        """Start capturing deterministic writes."""
        self._replay.clear()
        self._capturing = True

    def record_write(self, sql: str, parameters: Iterable[object] = ()) -> None:
        """Record a parameterized write while replay capture is enabled."""
        if self._capturing:
            self._replay.append(ReplayWrite(sql, tuple(parameters)))

    def stop_replay(self) -> tuple[ReplayWrite, ...]:
        """Stop capture and return an immutable write log."""
        self._capturing = False
        return tuple(self._replay)

    def replay(self, writes: Iterable[ReplayWrite]) -> None:
        """Replay captured writes transactionally on the current schema."""
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for write in writes:
                connection.execute(write.sql, write.parameters)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _rollback_for(statement: str) -> str | None:
        """Generate rollback SQL for common additive SQLite schema changes."""
        tokens = statement.rstrip(";").split()
        if len(tokens) >= 3 and tokens[0].upper() == "CREATE" and tokens[1].upper() == "TABLE":
            return f"DROP TABLE IF EXISTS {tokens[2]}"
        if len(tokens) >= 3 and tokens[0].upper() == "CREATE" and tokens[1].upper() == "INDEX":
            return f"DROP INDEX IF EXISTS {tokens[2]}"
        return None

    def rollback_sql(self, plan: MigrationPlan) -> tuple[str, ...]:
        """Return generated rollback statements for a migration plan."""
        return plan.rollback_statements
