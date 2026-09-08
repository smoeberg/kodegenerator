"""Add authoritative active project scope state (SC-101B).

Revision ID: 034_project_active_scope
Revises: 033_onboarding_project_identity
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034_project_active_scope"
down_revision = "033_onboarding_project_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("active_plan_request_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("active_scope_activated_by", sa.String(128), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("active_scope_activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("active_scope_command_id", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    active = bind.execute(
        sa.text(
            'SELECT COUNT(*) FROM "projects" '
            'WHERE active_plan_request_fingerprint IS NOT NULL'
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            "cannot downgrade: active project scope provenance would be lost"
        )
    op.drop_column("projects", "active_scope_command_id")
    op.drop_column("projects", "active_scope_activated_at")
    op.drop_column("projects", "active_scope_activated_by")
    op.drop_column("projects", "active_plan_request_fingerprint")
