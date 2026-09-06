from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_requirement_traceability_migration_upgrades_and_downgrades(tmp_path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'traceability.db'}")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))

    command.upgrade(cfg, "029_requirement_traceability")
    inspector = inspect(engine)
    table = "requirement_traceability_manifests"
    assert table in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns(table)}
    assert {
        "manifest_id",
        "organization_id",
        "certificate_id",
        "candidate_id",
        "plan_id",
        "plan_request_fingerprint",
        "command_id",
        "status",
        "created_by",
        "created_at",
        "requirements_payload",
        "links_payload",
        "manifest_payload",
    } <= columns

    command.downgrade(cfg, "028_delivery_certificates")
    assert table not in inspect(engine).get_table_names()
    assert "delivery_certificates" in inspect(engine).get_table_names()


def test_requirement_traceability_migration_forces_postgres_rls() -> None:
    source = Path("alembic/versions/029_requirement_traceability.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('dor.organization_id'" in source
    assert "WITH CHECK" in source
    assert "delivery_certificates.certificate_id" in source
