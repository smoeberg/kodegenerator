"""Phase 7 durable runtime queue.

Revision ID: 008_phase7_runtime_queue
Revises: 007_control_plane_projects
"""

import sqlalchemy as sa
from alembic import op

revision = "008_phase7_runtime_queue"
down_revision = "007_control_plane_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_queue_messages",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_queue_messages_topic", "runtime_queue_messages", ["topic"])
    op.create_index("ix_runtime_queue_messages_status", "runtime_queue_messages", ["status"])
    op.create_index("ix_runtime_queue_messages_available_at", "runtime_queue_messages", ["available_at"])
    op.create_index("ix_runtime_queue_messages_worker_id", "runtime_queue_messages", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_runtime_queue_messages_worker_id", table_name="runtime_queue_messages")
    op.drop_index("ix_runtime_queue_messages_available_at", table_name="runtime_queue_messages")
    op.drop_index("ix_runtime_queue_messages_status", table_name="runtime_queue_messages")
    op.drop_index("ix_runtime_queue_messages_topic", table_name="runtime_queue_messages")
    op.drop_table("runtime_queue_messages")
