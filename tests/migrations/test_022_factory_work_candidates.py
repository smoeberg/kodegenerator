from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_upgrade_and_downgrade(tmp_path: Path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'factory.db'}")
    command.upgrade(cfg, "022_factory_work_candidates")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    assert {
        "factory_work_packages",
        "factory_candidate_deliveries",
        "factory_candidate_selections",
    } <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "021_bot_evaluation_performance")
    assert "factory_work_packages" not in set(inspect(engine).get_table_names())


def test_migration_forces_rls() -> None:
    source = Path("alembic/versions/022_factory_work_candidates.py").read_text()
    assert (
        "ENABLE ROW LEVEL SECURITY" in source and "FORCE ROW LEVEL SECURITY" in source
    )
