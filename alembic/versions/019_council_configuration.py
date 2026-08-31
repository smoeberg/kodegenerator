"""Add versioned tenant-scoped Council configuration.

Revision ID: 019_council_configuration
Revises: 018_bot_catalog
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "019_council_configuration"
down_revision = "018_bot_catalog"
branch_labels = None
depends_on = None

TABLES = (
    "council_role_configurations",
    "council_templates",
    "council_role_allocations",
    "council_role_allocation_members",
)
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "council_role_configurations",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("protocol_function", sa.String(64), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        sa.Column("input_schema_ref", sa.Text()),
        sa.Column("output_schema_ref", sa.Text(), nullable=False),
        sa.Column("rubric_ref", sa.Text(), nullable=False),
        sa.Column("independent_verification", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "role_id", "version"),
        sa.CheckConstraint("version >= 1", name="ck_council_role_version_positive"),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_council_role_fingerprint"
        ),
    )
    op.create_table(
        "council_templates",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "template_id", "version"),
        sa.CheckConstraint("version >= 1", name="ck_council_template_version_positive"),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_council_template_fingerprint"
        ),
    )
    op.create_table(
        "council_role_allocations",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("allocation_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("role_version", sa.Integer(), nullable=False),
        sa.Column("independence_level", sa.String(32), nullable=False),
        sa.Column("autonomy_level", sa.Integer(), nullable=False),
        sa.Column("hard_constraints", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "allocation_id", "version"),
        sa.ForeignKeyConstraint(
            ["organization_id", "role_id", "role_version"],
            [
                "council_role_configurations.organization_id",
                "council_role_configurations.role_id",
                "council_role_configurations.version",
            ],
            name="fk_council_allocation_role_version",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_council_allocation_version_positive"
        ),
        sa.CheckConstraint(
            "autonomy_level BETWEEN 0 AND 5", name="ck_council_autonomy_range"
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_council_allocation_fingerprint"
        ),
    )
    op.create_table(
        "council_role_allocation_members",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("allocation_id", sa.String(128), nullable=False),
        sa.Column("allocation_version", sa.Integer(), nullable=False),
        sa.Column("bot_profile_id", sa.String(128), nullable=False),
        sa.Column("bot_profile_version", sa.Integer(), nullable=False),
        sa.Column("preference_rank", sa.Integer(), nullable=False),
        sa.Column("fallback_rank", sa.Integer()),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "allocation_id",
            "allocation_version",
            "bot_profile_id",
            "bot_profile_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "allocation_id", "allocation_version"],
            [
                "council_role_allocations.organization_id",
                "council_role_allocations.allocation_id",
                "council_role_allocations.version",
            ],
            name="fk_council_member_allocation_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "bot_profile_id", "bot_profile_version"],
            [
                "bot_profiles.organization_id",
                "bot_profiles.bot_profile_id",
                "bot_profiles.version",
            ],
            name="fk_council_member_profile_version",
        ),
        sa.CheckConstraint(
            "preference_rank >= 1", name="ck_council_member_preference_positive"
        ),
        sa.CheckConstraint(
            "fallback_rank IS NULL OR fallback_rank >= 1",
            name="ck_council_member_fallback_positive",
        ),
    )
    for table in TABLES:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    _enable_rls()


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        if bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one():
            raise RuntimeError(f"cannot downgrade: {table} contains rows")
    if bind.dialect.name == "postgresql":
        for table in reversed(TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in reversed(TABLES):
        op.drop_table(table)


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    predicate = (
        "organization_id = nullif(current_setting('dor.organization_id', true), '')"
    )
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
