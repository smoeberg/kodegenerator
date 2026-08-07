"""P3-14 task execution receipts.

Revision ID: 003_p3_14_task_execution
Revises: 002b_authority_organization_scope
"""
from alembic import op
import sqlalchemy as sa

revision = "003_p3_14_task_execution"
down_revision = "002b_authority_organization_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_executions",
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=128), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("resource_organization_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint("execution_id", "organization_id", name="uq_task_execution_org_id"),
    )
    op.create_index("ix_task_executions_organization_id", "task_executions", ["organization_id"])
    op.create_index("ix_task_executions_actor_id", "task_executions", ["actor_id"])
    op.create_index("ix_task_executions_status", "task_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_task_executions_status", table_name="task_executions")
    op.drop_index("ix_task_executions_actor_id", table_name="task_executions")
    op.drop_index("ix_task_executions_organization_id", table_name="task_executions")
    op.drop_table("task_executions")
