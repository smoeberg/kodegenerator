"""Add tenant-scoped durable WorkUnit records (WQ-102).

Revision ID: 031_work_units
Revises: 030_artifact_acceptances
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "031_work_units"
down_revision = "030_artifact_acceptances"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "work_units",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("work_unit_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("required_capability", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("depends_on_snapshot", sa.JSON(), nullable=False),
        sa.Column("base_version", sa.JSON(), nullable=True),
        sa.Column("allowed_resources", sa.JSON(), nullable=False),
        sa.Column("acceptance_refs", sa.JSON(), nullable=False),
        sa.Column("delivered_artifact_version", sa.JSON(), nullable=True),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("lease", sa.JSON(), nullable=True),
        sa.Column("previous_worker", sa.String(128), nullable=True),
        sa.Column("rework_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "work_unit_id"),
    )
    op.create_index(
        "ix_work_units_organization_id",
        "work_units",
        ["organization_id"],
    )
    op.create_index(
        "ix_work_units_state",
        "work_units",
        ["state"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "work_units" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "work_units" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "work_units" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "work_units"')).scalar_one():
        raise RuntimeError("cannot downgrade: work_units contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "work_units"')
        op.execute('ALTER TABLE "work_units" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "work_units" DISABLE ROW LEVEL SECURITY')
    op.drop_index(
        "ix_work_units_state",
        table_name="work_units",
    )
    op.drop_index(
        "ix_work_units_organization_id",
        table_name="work_units",
    )
    op.drop_table("work_units")
