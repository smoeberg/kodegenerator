from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_worker_identity_migration_upgrades_and_downgrades(tmp_path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'identity.db'}")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    command.upgrade(cfg, "024_worker_service_identities")
    assert "worker_service_identities" in inspect(engine).get_table_names()

    command.downgrade(cfg, "023_factory_integration")
    assert "worker_service_identities" not in inspect(engine).get_table_names()


def test_worker_identity_migration_forces_postgres_rls() -> None:
    source = Path("alembic/versions/024_worker_service_identities.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('dor.organization_id'" in source
