"""Add lease fencing to the durable runtime queue.

Revision ID: 010_runtime_queue_fencing
Revises: 009_p4_execution_replay_ledger
"""

import sqlalchemy as sa

from alembic import op

revision = "010_runtime_queue_fencing"
down_revision = "009_p4_execution_replay_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_queue_messages",
        sa.Column("lease_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_runtime_queue_messages_lease_id",
        "runtime_queue_messages",
        ["lease_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_queue_messages_lease_id",
        table_name="runtime_queue_messages",
    )
    op.drop_column("runtime_queue_messages", "lease_id")
