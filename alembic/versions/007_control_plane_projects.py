"""Add durable projects for Control Plane API v1.

Revision ID: 007_control_plane_projects
Revises: 006_merge_heads
"""

import sqlalchemy as sa

from alembic import op

revision = "007_control_plane_projects"
down_revision = "006_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("intent_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("project_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("launched_by", sa.String(length=128), nullable=True),
        sa.Column("launch_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("launch_command_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_project_org_id"),
    )
    op.create_index(
        "ix_projects_organization_id",
        "projects",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_projects_status",
        "projects",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_table("projects")
