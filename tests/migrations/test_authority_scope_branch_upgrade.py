from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).parents[2]


def _upgrade(database: Path, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _downgrade(database: Path, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _assert_authority_scope(database: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{database}")
    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("role_definitions")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("role_definitions")
    }
    indexes = {index["name"] for index in inspector.get_indexes("role_definitions")}
    with engine.connect() as connection:
        heads = set(
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalars()
        )
    engine.dispose()

    assert "organization_id" in columns
    assert "uq_role_definition_org_id" in unique_constraints
    assert "ix_role_definitions_organization_id" in indexes
    assert heads == {"025_swarm_control_state"}


def test_upgrade_converges_when_005_branch_was_applied_first(tmp_path: Path) -> None:
    database = tmp_path / "authority-005-first.db"

    _upgrade(database, "005_authority_org_scope")
    _upgrade(database, "head")

    _assert_authority_scope(database)


def test_upgrade_converges_when_002b_branch_was_applied_first(tmp_path: Path) -> None:
    database = tmp_path / "authority-002b-first.db"

    _upgrade(database, "002b_authority_organization_scope")
    _upgrade(database, "head")

    _assert_authority_scope(database)


def test_fresh_database_upgrade_still_reaches_canonical_head(tmp_path: Path) -> None:
    database = tmp_path / "authority-fresh.db"

    _upgrade(database, "head")

    _assert_authority_scope(database)


def test_parallel_authority_branches_can_downgrade_to_base(tmp_path: Path) -> None:
    database = tmp_path / "authority-downgrade.db"

    _upgrade(database, "head")
    _downgrade(database, "base")

    engine = sa.create_engine(f"sqlite:///{database}")
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
