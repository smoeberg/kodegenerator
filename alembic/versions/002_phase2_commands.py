"""Phase 2 command execution records.

Revision ID: 002_phase2_commands
Revises: 001_phase1_core
"""
from alembic import op
import sqlalchemy as sa


revision = "002_phase2_commands"
down_revision = "001_phase1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "command_executions",
        sa.Column("command_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("command_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.create_index(
        "ix_command_executions_organization_id",
        "command_executions",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_command_executions_organization_id",
        table_name="command_executions",
    )
    op.drop_table("command_executions")
