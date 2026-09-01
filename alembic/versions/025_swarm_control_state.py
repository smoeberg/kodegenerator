"""Add identity tenant binding and durable Swarm control state.

Revision ID: 025_swarm_control_state
Revises: 024_worker_service_identities
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "025_swarm_control_state"
down_revision = "024_worker_service_identities"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.add_column(
        "identity_principals",
        sa.Column("organization_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_identity_principals_organization_id",
        "identity_principals",
        ["organization_id"],
    )
    op.create_table(
        "swarm_project_dispatches",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_swarm_dispatch_project",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "project_id"),
    )
    op.create_index(
        "ix_swarm_project_dispatches_owner_id",
        "swarm_project_dispatches",
        ["owner_id"],
    )
    op.create_table(
        "swarm_dispatch_controls",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        for table in ("swarm_project_dispatches", "swarm_dispatch_controls"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY "{POLICY}" ON "{table}" '
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("swarm_project_dispatches", "swarm_dispatch_controls"):
        if bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one():
            raise RuntimeError(f"cannot downgrade: {table} contains rows")
    if bind.dialect.name == "postgresql":
        for table in ("swarm_project_dispatches", "swarm_dispatch_controls"):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("swarm_dispatch_controls")
    op.drop_table("swarm_project_dispatches")
    op.drop_index(
        "ix_identity_principals_organization_id", table_name="identity_principals"
    )
    op.drop_column("identity_principals", "organization_id")
