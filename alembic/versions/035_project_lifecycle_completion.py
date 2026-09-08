"""Add governed project lifecycle and immutable completion proof (PC-101).

Revision ID: 035_project_lifecycle_completion
Revises: 034_project_active_scope
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035_project_lifecycle_completion"
down_revision = "034_project_active_scope"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    for column in (
        sa.Column("completion_requested_by", sa.String(128), nullable=True),
        sa.Column("completion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_request_command_id", sa.String(128), nullable=True),
        sa.Column("completion_record_id", sa.String(64), nullable=True),
        sa.Column("completed_by", sa.String(128), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.String(128), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_command_id", sa.String(128), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("archived_by", sa.String(128), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_command_id", sa.String(128), nullable=True),
        sa.Column("archived_from_status", sa.String(32), nullable=True),
        sa.Column("continued_from_project_id", sa.String(128), nullable=True),
    ):
        op.add_column("projects", column)

    op.create_index(
        "ix_projects_continued_from_project_id",
        "projects",
        ["continued_from_project_id"],
        unique=False,
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("projects") as batch_op:
            batch_op.create_foreign_key(
                "fk_project_continuation_org",
                "projects",
                ["organization_id", "continued_from_project_id"],
                ["organization_id", "id"],
            )
    else:
        op.create_foreign_key(
            "fk_project_continuation_org",
            "projects",
            "projects",
            ["organization_id", "continued_from_project_id"],
            ["organization_id", "id"],
        )

    op.create_table(
        "project_completion_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("final_project_revision", sa.Integer(), nullable=False),
        sa.Column("onboarding_intent_id", sa.String(128), nullable=False),
        sa.Column("plan_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("repository_commit_sha", sa.String(64), nullable=False),
        sa.Column("delivery_certificate_ids", sa.JSON(), nullable=False),
        sa.Column("traceability_manifest_ids", sa.JSON(), nullable=False),
        sa.Column("integration_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("completed_by", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_project_completion_project_org",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            name="uq_project_completion_org_project",
        ),
    )
    op.create_index(
        "ix_project_completion_records_organization_id",
        "project_completion_records",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_completion_records_project_id",
        "project_completion_records",
        ["project_id"],
        unique=False,
    )

    if bind.dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute(
            'ALTER TABLE "project_completion_records" ENABLE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "project_completion_records" FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "project_completion_records" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    terminal = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM projects WHERE status IN "
            "('completion_pending','completed','cancelled','archived') "
            "OR continued_from_project_id IS NOT NULL"
        )
    ).scalar_one()
    completion_records = bind.execute(
        sa.text("SELECT COUNT(*) FROM project_completion_records")
    ).scalar_one()
    if terminal or completion_records:
        raise RuntimeError(
            "cannot downgrade: PC-101 lifecycle/completion provenance would be lost"
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            f'DROP POLICY IF EXISTS "{POLICY}" ON "project_completion_records"'
        )
        op.execute(
            'ALTER TABLE "project_completion_records" NO FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "project_completion_records" DISABLE ROW LEVEL SECURITY'
        )
    op.drop_index(
        "ix_project_completion_records_project_id",
        table_name="project_completion_records",
    )
    op.drop_index(
        "ix_project_completion_records_organization_id",
        table_name="project_completion_records",
    )
    op.drop_table("project_completion_records")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("projects") as batch_op:
            batch_op.drop_constraint(
                "fk_project_continuation_org",
                type_="foreignkey",
            )
    else:
        op.drop_constraint(
            "fk_project_continuation_org",
            "projects",
            type_="foreignkey",
        )
    op.drop_index("ix_projects_continued_from_project_id", table_name="projects")
    for column in (
        "continued_from_project_id",
        "archived_from_status",
        "archive_command_id",
        "archived_at",
        "archived_by",
        "cancellation_reason",
        "cancel_command_id",
        "cancelled_at",
        "cancelled_by",
        "completed_at",
        "completed_by",
        "completion_record_id",
        "completion_request_command_id",
        "completion_requested_at",
        "completion_requested_by",
    ):
        op.drop_column("projects", column)
