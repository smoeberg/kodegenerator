"""Merge the P3-14 task execution and authority organization-scope heads."""

from alembic import op

revision = "006_merge_heads"
down_revision = ("003_p3_14_task_execution", "005_authority_org_scope")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
