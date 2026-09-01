"""Add tenant-scoped worker service identities.

Revision ID: 024_worker_service_identities
Revises: 023_factory_integration
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "024_worker_service_identities"
down_revision = "023_factory_integration"
branch_labels = None
depends_on = None
TABLE = "worker_service_identities"
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("service_id", sa.String(128), nullable=False),
        sa.Column("credential_hash", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "service_id"),
    )
    op.create_index(f"ix_{TABLE}_organization_id", TABLE, ["organization_id"])
    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "{TABLE}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{TABLE}"')).scalar_one()
    if count:
        raise RuntimeError(f"cannot downgrade: {TABLE} contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "{TABLE}"')
        op.execute(f'ALTER TABLE "{TABLE}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{TABLE}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(TABLE)
