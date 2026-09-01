"""Readiness checks for canonical database connectivity and schema state."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text


def expected_alembic_head() -> str:
    contract = Path(__file__).parents[1] / "docs" / "CURRENT_STATE.json"
    payload = json.loads(contract.read_text(encoding="utf-8"))
    value = payload.get("canonical_alembic_head")
    if not isinstance(value, str) or not value:
        raise RuntimeError("canonical Alembic head is not configured")
    return value


def verify_database_readiness(database) -> str:
    """Return the verified head or raise without disclosing connection data."""
    expected = expected_alembic_head()
    with database.session() as session:
        session.execute(text("SELECT 1"))
        rows = session.execute(text("SELECT version_num FROM alembic_version"))
        heads = {str(row[0]) for row in rows}
    if heads != {expected}:
        raise RuntimeError("database schema is not at the canonical Alembic head")
    return expected
