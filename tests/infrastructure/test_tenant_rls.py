"""Database-enforced tenant isolation contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from infrastructure.persistence.database import Database, apply_tenant_context


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "015_core_tenant_rls.py"
EXTENDED_MIGRATION = (
    ROOT / "alembic" / "versions" / "016_extended_tenant_rls.py"
)


class _RecordingSession:
    def __init__(self, dialect_name: str = "postgresql") -> None:
        self.info: dict[str, object] = {}
        self.executions: list[tuple[str, dict[str, str]]] = []
        self.closed = False
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))

    def execute(self, statement, parameters):
        self.executions.append((str(statement), parameters))

    def close(self) -> None:
        self.closed = True

    def get_bind(self):
        return self._bind


def test_postgres_session_sets_transaction_local_tenant() -> None:
    session = _RecordingSession()
    database = Database.__new__(Database)
    database.engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    database.session_factory = lambda: session

    with database.session(" org-a ") as scoped:
        assert scoped.info["organization_id"] == "org-a"

    assert session.executions == [
        (
            "SELECT set_config('dor.organization_id', :organization_id, true)",
            {"organization_id": "org-a"},
        )
    ]
    assert session.closed is True


def test_sqlite_session_retains_repository_scope_without_set_config() -> None:
    database = Database("sqlite://")

    with database.session("org-a") as session:
        assert session.info["organization_id"] == "org-a"
        assert session.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("organization_id", ["", "   ", "x" * 129])
def test_session_rejects_invalid_tenant_context(organization_id: str) -> None:
    database = Database("sqlite://")

    with pytest.raises(ValueError, match="organization_id"):
        with database.session(organization_id):
            pass


def test_rls_migration_forces_one_policy_per_canonical_table() -> None:
    migration = _load_migration()
    executed: list[str] = []
    migration.op = _FakeOp("postgresql", executed)

    migration.upgrade()

    assert len(executed) == len(migration.TENANT_TABLES) * 3
    for table in migration.TENANT_TABLES:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in executed
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in executed
        policy = next(
            sql for sql in executed if sql.startswith("CREATE POLICY") and f'"{table}"' in sql
        )
        assert "current_setting('dor.organization_id', true)" in policy
        assert "WITH CHECK" in policy


def test_rls_migration_is_noop_for_sqlite() -> None:
    migration = _load_migration()
    executed: list[str] = []
    migration.op = _FakeOp("sqlite", executed)

    migration.upgrade()
    migration.downgrade()

    assert executed == []


def test_extended_rls_covers_pipeline_and_council_tables() -> None:
    migration = _load_migration(EXTENDED_MIGRATION)
    executed: list[str] = []
    migration.op = _FakeOp("postgresql", executed)

    migration.upgrade()

    assert len(migration.TENANT_TABLES) == 9
    assert len(executed) == len(migration.TENANT_TABLES) * 3
    for table in migration.TENANT_TABLES:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in executed
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in executed


def test_tenant_context_cannot_be_rebound_to_another_organization() -> None:
    session = _RecordingSession("sqlite")
    apply_tenant_context(session, "org-a")

    with pytest.raises(RuntimeError, match="another organization"):
        apply_tenant_context(session, "org-b")


def test_separate_stores_apply_tenant_context_at_every_session_boundary() -> None:
    paths = (
        "infrastructure/persistence/pipeline_state_store.py",
        "infrastructure/persistence/llm_replay_store.py",
        "infrastructure/persistence/side_effect_store.py",
        "phase4/council/store.py",
        "phase4/council/execution_events.py",
    )
    for path in paths:
        source = (ROOT / path).read_text(encoding="utf-8")
        session_boundaries = source.count("() as session") + source.count(
            "() as db"
        )
        assert session_boundaries > 0
        assert source.count("apply_tenant_context(") == session_boundaries


def test_canonical_runtime_never_opens_unscoped_tenant_sessions() -> None:
    authority = (ROOT / "runtime" / "authority.py").read_text(encoding="utf-8")
    projects = (ROOT / "runtime" / "project_runtime.py").read_text(encoding="utf-8")
    commands = (ROOT / "runtime" / "command_runtime_impl.py").read_text(
        encoding="utf-8"
    )
    core = (ROOT / "runtime" / "core.py").read_text(encoding="utf-8")

    assert ".database.session()" not in authority
    assert ".database.session()" not in projects
    assert ".database.session()" not in commands
    # The sole unscoped core transaction creates the organization catalog row;
    # it does not access an RLS-protected tenant table.
    assert core.count("self.database.session()") == 1


class _FakeOp:
    def __init__(self, dialect_name: str, executed: list[str]) -> None:
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self._executed = executed

    def get_bind(self):
        return self._bind

    def execute(self, statement: str) -> None:
        self._executed.append(statement)


def _load_migration(path: Path = MIGRATION):
    spec = importlib.util.spec_from_file_location(
        f"tenant_rls_migration_{path.stem}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
