from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_upgrade_and_downgrade(tmp_path: Path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'integration.db'}")
    command.upgrade(cfg, "023_factory_integration")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    assert {
        "factory_integration_plans",
        "factory_integration_receipts",
    } <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "022_factory_work_candidates")
    assert "factory_integration_plans" not in set(inspect(engine).get_table_names())


def test_migration_forces_rls() -> None:
    source = Path("alembic/versions/023_factory_integration.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
