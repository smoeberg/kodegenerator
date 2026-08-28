"""Add fenced terminal side-effect receipts.

Revision ID: 013_terminal_side_effects
Revises: 012_pipeline_persistence
"""

import sqlalchemy as sa

from alembic import op

revision = "013_terminal_side_effects"
down_revision = "012_pipeline_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terminal_side_effects",
        sa.Column("organization_id", sa.String(length=128), primary_key=True),
        sa.Column("action", sa.String(length=64), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=255), primary_key=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.String(length=64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("failure_class", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_terminal_side_effects_status", "terminal_side_effects", ["status"]
    )
    op.create_index(
        "ix_terminal_side_effects_lease_expires_at",
        "terminal_side_effects",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_terminal_side_effects_lease_expires_at", table_name="terminal_side_effects"
    )
    op.drop_index("ix_terminal_side_effects_status", table_name="terminal_side_effects")
    op.drop_table("terminal_side_effects")
