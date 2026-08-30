"""Tenant-scope migration contract for queue and replay state."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "017_queue_replay_tenant_scope.py"


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _Bind:
    def __init__(self, dialect: str, row_count: int) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.row_count = row_count

    def execute(self, _statement) -> _ScalarResult:
        return _ScalarResult(self.row_count)


class _RecordingOp:
    def __init__(self, *, dialect: str = "postgresql", row_count: int = 0) -> None:
        self.bind = _Bind(dialect, row_count)
        self.executed: list[str] = []
        self.created: dict[str, tuple[object, ...]] = {}
        self.dropped: list[str] = []
        self.indexes: list[tuple[str, str, tuple[str, ...]]] = []

    def get_bind(self):
        return self.bind

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def create_table(self, name: str, *elements) -> None:
        self.created[name] = elements

    def drop_table(self, name: str) -> None:
        self.dropped.append(name)

    def create_index(self, name: str, table: str, columns: list[str]) -> None:
        self.indexes.append((name, table, tuple(columns)))


def _load_migration():
    spec = importlib.util.spec_from_file_location("queue_replay_scope", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_refuses_to_invent_tenant_for_existing_rows() -> None:
    migration = _load_migration()
    operation = _RecordingOp(row_count=1)
    migration.op = operation

    with pytest.raises(RuntimeError, match="drain or explicitly archive"):
        migration.upgrade()

    assert operation.dropped == []
    assert operation.created == {}


def test_migration_creates_composite_tenant_keys_and_forced_rls() -> None:
    migration = _load_migration()
    operation = _RecordingOp()
    migration.op = operation

    migration.upgrade()

    assert set(operation.created) == set(migration.TENANT_TABLES)
    for table, logical_id in (
        ("runtime_queue_messages", "id"),
        ("execution_replay_ledger", "execution_id"),
    ):
        elements = operation.created[table]
        columns = {element.name for element in elements if hasattr(element, "name")}
        assert {"organization_id", logical_id} <= columns
        primary_key = next(
            element for element in elements if type(element).__name__ == "PrimaryKeyConstraint"
        )
        assert tuple(primary_key._pending_colargs) == (  # noqa: SLF001
            "organization_id",
            logical_id,
        )
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in operation.executed
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in operation.executed
        policy = next(
            statement
            for statement in operation.executed
            if statement.startswith("CREATE POLICY") and f'"{table}"' in statement
        )
        assert "current_setting('dor.organization_id', true)" in policy
        assert "WITH CHECK" in policy
