"""Add tenant-scoped runtime settings for GUI-managed configuration.

Revision ID: 036_runtime_settings
Revises: 035_project_lifecycle_completion
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_runtime_settings"
down_revision = "035_project_lifecycle_completion"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("setting_key", sa.String(128), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "setting_key"),
        sa.ForeignKeyConstraint(
            ["organization_id", "updated_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_runtime_settings_actor_org",
        ),
    )
    op.create_index(
        "ix_runtime_settings_organization_id",
        "runtime_settings",
        ["organization_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "runtime_settings" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "runtime_settings" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "runtime_settings" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "runtime_settings"')).scalar_one():
        raise RuntimeError("cannot downgrade: runtime_settings contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "runtime_settings"')
        op.execute('ALTER TABLE "runtime_settings" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "runtime_settings" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_runtime_settings_organization_id", table_name="runtime_settings")
    op.drop_table("runtime_settings")
