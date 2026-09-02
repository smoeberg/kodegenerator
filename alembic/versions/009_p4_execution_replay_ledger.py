"""Create the durable P4-01 execution replay ledger.

Revision ID: 009_p4_execution_replay_ledger
Revises: 008_phase7_runtime_queue
"""

import sqlalchemy as sa
from alembic import op

revision = "009_p4_execution_replay_ledger"
down_revision = "008_phase7_runtime_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_replay_ledger",
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("grant_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.String(length=64), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index("ix_execution_replay_ledger_status", "execution_replay_ledger", ["status"])
    op.create_index("ix_execution_replay_ledger_lease_expires_at", "execution_replay_ledger", ["lease_expires_at"])
    op.create_index("ix_execution_replay_ledger_request_id", "execution_replay_ledger", ["request_id"])
    op.create_index("ix_execution_replay_ledger_grant_id", "execution_replay_ledger", ["grant_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_replay_ledger_grant_id", table_name="execution_replay_ledger")
    op.drop_index("ix_execution_replay_ledger_request_id", table_name="execution_replay_ledger")
    op.drop_index("ix_execution_replay_ledger_lease_expires_at", table_name="execution_replay_ledger")
    op.drop_index("ix_execution_replay_ledger_status", table_name="execution_replay_ledger")
    op.drop_table("execution_replay_ledger")
