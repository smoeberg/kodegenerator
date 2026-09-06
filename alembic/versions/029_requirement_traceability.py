"""Add immutable tenant-scoped requirement traceability manifests.

Revision ID: 029_requirement_traceability
Revises: 028_delivery_certificates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "029_requirement_traceability"
down_revision = "028_delivery_certificates"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "requirement_traceability_manifests",
        sa.Column("manifest_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("certificate_id", sa.String(64), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("command_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requirements_payload", sa.JSON(), nullable=False),
        sa.Column("links_payload", sa.JSON(), nullable=False),
        sa.Column("manifest_payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("manifest_id"),
        sa.UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_requirement_traceability_command",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_id"],
            ["delivery_certificates.certificate_id"],
            name="fk_requirement_traceability_certificate",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_requirement_traceability_actor_org",
        ),
    )
    op.create_index(
        "ix_requirement_traceability_organization_id",
        "requirement_traceability_manifests",
        ["organization_id"],
    )
    op.create_index(
        "ix_requirement_traceability_certificate_id",
        "requirement_traceability_manifests",
        ["certificate_id"],
    )
    op.create_index(
        "ix_requirement_traceability_candidate_id",
        "requirement_traceability_manifests",
        ["candidate_id"],
    )
    op.create_index(
        "ix_requirement_traceability_plan_id",
        "requirement_traceability_manifests",
        ["plan_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute(
            'ALTER TABLE "requirement_traceability_manifests" ENABLE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "requirement_traceability_manifests" FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "requirement_traceability_manifests" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text('SELECT COUNT(*) FROM "requirement_traceability_manifests"')
    ).scalar_one():
        raise RuntimeError(
            "cannot downgrade: requirement_traceability_manifests contains rows"
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            f'DROP POLICY IF EXISTS "{POLICY}" ON "requirement_traceability_manifests"'
        )
        op.execute(
            'ALTER TABLE "requirement_traceability_manifests" NO FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "requirement_traceability_manifests" DISABLE ROW LEVEL SECURITY'
        )
    for index_name in (
        "ix_requirement_traceability_plan_id",
        "ix_requirement_traceability_candidate_id",
        "ix_requirement_traceability_certificate_id",
        "ix_requirement_traceability_organization_id",
    ):
        op.drop_index(index_name, table_name="requirement_traceability_manifests")
    op.drop_table("requirement_traceability_manifests")
