"""Add tenant-scoped immutable WorkUnit revision history (WQ-102).

Revision ID: 032_work_unit_revisions
Revises: 031_work_units
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032_work_unit_revisions"
down_revision = "031_work_units"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "work_unit_revisions",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("work_unit_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "work_unit_id", "revision"),
    )
    op.create_index(
        "ix_work_unit_revisions_org_id",
        "work_unit_revisions",
        ["organization_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "work_unit_revisions" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "work_unit_revisions" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "work_unit_revisions" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "work_unit_revisions"')).scalar_one():
        raise RuntimeError("cannot downgrade: work_unit_revisions contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "work_unit_revisions"')
        op.execute('ALTER TABLE "work_unit_revisions" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "work_unit_revisions" DISABLE ROW LEVEL SECURITY')
    op.drop_index(
        "ix_work_unit_revisions_org_id",
        table_name="work_unit_revisions",
    )
    op.drop_table("work_unit_revisions")
