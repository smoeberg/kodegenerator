"""Add project_id identity to onboarding intents (WQ-104).

Revision ID: 033_onboarding_project_identity
Revises: 032_work_unit_revisions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033_onboarding_project_identity"
down_revision = "032_work_unit_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "onboarding_intents" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("onboarding_intents")]
        if "project_id" not in columns:
            op.add_column(
                "onboarding_intents",
                sa.Column("project_id", sa.String(128), nullable=False, server_default="project-1"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "onboarding_intents" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("onboarding_intents")]
        if "project_id" in columns:
            op.drop_column("onboarding_intents", "project_id")
