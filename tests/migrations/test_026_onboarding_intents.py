from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_onboarding_intent_migration_upgrades_and_downgrades(tmp_path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'onboarding.db'}")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))

    command.upgrade(cfg, "026_onboarding_intents")
    inspector = inspect(engine)
    assert "onboarding_intents" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("onboarding_intents")}
    assert {
        "intent_id",
        "organization_id",
        "source_repository",
        "purpose",
        "rationale",
        "target_stack",
        "supersedes_intent_id",
        "content_fingerprint",
        "declared_by",
        "declared_at",
    } <= columns
    indexes = {index["name"] for index in inspector.get_indexes("onboarding_intents")}
    assert "uq_onboarding_intent_root_repository" in indexes

    command.downgrade(cfg, "025_swarm_control_state")
    assert "onboarding_intents" not in inspect(engine).get_table_names()


def test_onboarding_intent_migration_forces_postgres_rls() -> None:
    source = Path("alembic/versions/026_onboarding_intents.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('dor.organization_id'" in source
    assert "WITH CHECK" in source


def test_current_state_tracks_onboarding_intent_migration_head() -> None:
    source = Path("docs/CURRENT_STATE.json").read_text()
    assert '"canonical_alembic_head": "026_onboarding_intents"' in source
