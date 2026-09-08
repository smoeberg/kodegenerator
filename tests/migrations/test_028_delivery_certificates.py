from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_delivery_certificate_migration_upgrades_and_downgrades(tmp_path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'delivery.db'}")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))

    command.upgrade(cfg, "028_delivery_certificates")
    inspector = inspect(engine)
    assert "delivery_certificates" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("delivery_certificates")}
    assert {
        "certificate_id",
        "organization_id",
        "candidate_id",
        "contract_id",
        "contract_version",
        "contract_fingerprint",
        "result",
        "command_id",
        "certified_by",
        "certified_at",
        "reason_codes",
        "candidate_payload",
        "certificate_payload",
    } <= columns

    command.downgrade(cfg, "027_organization_memberships")
    assert "delivery_certificates" not in inspect(engine).get_table_names()


def test_delivery_certificate_migration_forces_postgres_rls() -> None:
    source = Path("alembic/versions/028_delivery_certificates.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('dor.organization_id'" in source
    assert "WITH CHECK" in source


def test_current_state_tracks_delivery_certificate_migration_head() -> None:
    source = Path("docs/CURRENT_STATE.json").read_text()
    assert '"canonical_alembic_head": "033_onboarding_project_identity"' in source
