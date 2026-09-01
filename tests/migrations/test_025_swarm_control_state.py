from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_swarm_control_migration_upgrades_and_downgrades(tmp_path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'control.db'}")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))

    command.upgrade(cfg, "025_swarm_control_state")
    tables = set(inspect(engine).get_table_names())
    assert {"swarm_project_dispatches", "swarm_dispatch_controls"} <= tables
    assert "organization_id" in {
        column["name"] for column in inspect(engine).get_columns("identity_principals")
    }

    command.downgrade(cfg, "024_worker_service_identities")
    assert "swarm_project_dispatches" not in inspect(engine).get_table_names()


def test_swarm_control_migration_forces_postgres_rls() -> None:
    source = Path("alembic/versions/025_swarm_control_state.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('dor.organization_id'" in source
