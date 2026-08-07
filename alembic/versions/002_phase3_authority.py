"""Phase 3 authority schema.

Revision ID: 002_phase3_authority
Revises: 001_phase1_core
"""
from alembic import op
import sqlalchemy as sa

revision = "002_phase3_authority"
down_revision = "001_phase1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_definitions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "role_assignments",
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("role_definition_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "organization_id", "role_definition_id"),
        sa.UniqueConstraint(
            "actor_id", "organization_id", "role_definition_id",
            name="uq_role_assignment_actor_org_role",
        ),
    )
    op.create_index(
        "ix_role_assignments_organization_id",
        "role_assignments",
        ["organization_id"],
    )
    op.create_index(
        "ix_role_assignments_role_definition_id",
        "role_assignments",
        ["role_definition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_role_assignments_role_definition_id",
        table_name="role_assignments",
    )
    op.drop_index(
        "ix_role_assignments_organization_id",
        table_name="role_assignments",
    )
    op.drop_table("role_assignments")
    op.drop_table("role_definitions")
