"""Tests for SQLite migration engine and snapshots."""
from __future__ import annotations

import sqlite3

from services.migration_engine import MigrationEngine
from services.schema_snapshot import SchemaSnapshot


def make_db(path: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO items(value) VALUES ('before')")
    connection.commit()
    connection.close()


def test_snapshot_verifies_and_restores(tmp_path):
    database = tmp_path / "db.sqlite"
    backup = tmp_path / "backup.sqlite"
    make_db(str(database))
    snapshot = SchemaSnapshot.create(database, backup)
    assert snapshot.verify()
    sqlite3.connect(database).execute("DROP TABLE items").connection.commit()
    snapshot.restore(database)
    assert sqlite3.connect(database).execute("SELECT value FROM items").fetchone() == ("before",)


def test_migration_applies_and_generates_rollback(tmp_path):
    database = tmp_path / "db.sqlite"
    make_db(str(database))
    engine = MigrationEngine(database, tmp_path / "backups")
    plan = engine.prepare(["CREATE TABLE audit (id INTEGER PRIMARY KEY)", "CREATE INDEX audit_id ON audit(id)"], "v2")
    engine.execute(plan)
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='audit'").fetchone() == ("audit",)
    assert "DROP TABLE IF EXISTS audit" in plan.rollback_statements
    connection.close()


def test_failed_validation_restores_database(tmp_path):
    database = tmp_path / "db.sqlite"
    make_db(str(database))
    engine = MigrationEngine(database, tmp_path / "backups")
    plan = engine.prepare(["CREATE TABLE new_table (id INTEGER PRIMARY KEY)"], "v3")
    try:
        engine.execute(plan, lambda _: False)
    except RuntimeError:
        pass
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='new_table'").fetchone() is None
    connection.close()


def test_replay_is_deterministic_and_transactional(tmp_path):
    database = tmp_path / "db.sqlite"
    make_db(str(database))
    engine = MigrationEngine(database, tmp_path / "backups")
    engine.start_replay()
    engine.record_write("INSERT INTO items(value) VALUES (?)", ("replayed",))
    writes = engine.stop_replay()
    engine.replay(writes)
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT value FROM items ORDER BY id").fetchall() == [("before",), ("replayed",)]
    connection.close()


def test_snapshot_checksum_detects_tampering(tmp_path):
    database = tmp_path / "db.sqlite"
    backup = tmp_path / "backup.sqlite"
    make_db(str(database))
    snapshot = SchemaSnapshot.create(database, backup)
    backup.write_bytes(backup.read_bytes() + b"tampered")
    assert snapshot.verify() is False
