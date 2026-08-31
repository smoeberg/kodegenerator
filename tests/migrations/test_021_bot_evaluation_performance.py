from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def config(tmp_path: Path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")
    return cfg


def test_upgrade_and_empty_downgrade(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    command.upgrade(cfg, "021_bot_evaluation_performance")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    names = set(inspect(engine).get_table_names())
    assert {
        "evaluation_rubrics",
        "evaluation_records",
        "bot_performance_observations",
        "bot_performance_snapshots",
    } <= names
    command.downgrade(cfg, "020_bot_selection_assignments")
    assert "evaluation_rubrics" not in set(inspect(engine).get_table_names())


def test_migration_declares_forced_rls() -> None:
    source = Path("alembic/versions/021_bot_evaluation_performance.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source


def test_downgrade_refuses_to_drop_evidence(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    command.upgrade(cfg, "021_bot_evaluation_performance")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evaluation_rubrics "
                "(organization_id,rubric_id,version,subject_classes,criteria,"
                "pass_threshold,independence_level,fingerprint,created_at) VALUES "
                "('org-1','r1',1,'[]','[]',1.0,'connection',:fp,:created)"
            ),
            {"fp": "a" * 64, "created": "2026-08-31T00:00:00+00:00"},
        )
    with pytest.raises(RuntimeError, match="contains rows"):
        command.downgrade(cfg, "020_bot_selection_assignments")
