"""Add immutable tenant-scoped Bot Catalog records.

Revision ID: 018_bot_catalog
Revises: 017_queue_replay_tenant_scope
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "018_bot_catalog"
down_revision = "017_queue_replay_tenant_scope"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "bot_provider_connections",
    "bot_model_deployments",
    "bot_profiles",
)
POLICY_NAME = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "bot_provider_connections",
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("secret_reference", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("data_boundary", sa.String(length=32), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "connection_id", "version"),
        sa.CheckConstraint("version >= 1", name="ck_bot_connection_version_positive"),
        sa.CheckConstraint(
            "concurrency_limit >= 1", name="ck_bot_connection_concurrency_positive"
        ),
    )
    op.create_table(
        "bot_model_deployments",
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("deployment_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.String(length=128), nullable=False),
        sa.Column("connection_version", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("model_family", sa.String(length=255), nullable=False),
        sa.Column("max_context_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("structured_output", sa.Boolean(), nullable=False),
        sa.Column("tool_capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "deployment_id", "revision"),
        sa.ForeignKeyConstraint(
            ["organization_id", "connection_id", "connection_version"],
            [
                "bot_provider_connections.organization_id",
                "bot_provider_connections.connection_id",
                "bot_provider_connections.version",
            ],
            name="fk_bot_deployment_connection_version",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_bot_deployment_revision_positive"),
        sa.CheckConstraint(
            "max_context_tokens >= 1", name="ck_bot_deployment_context_positive"
        ),
        sa.CheckConstraint(
            "max_output_tokens >= 1", name="ck_bot_deployment_output_positive"
        ),
    )
    op.create_table(
        "bot_profiles",
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("bot_profile_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("agent_identity", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("deployment_id", sa.String(length=128), nullable=False),
        sa.Column("deployment_revision", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("permitted_tools", sa.JSON(), nullable=False),
        sa.Column("data_policy", sa.JSON(), nullable=False),
        sa.Column("budget_policy", sa.JSON(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "bot_profile_id", "version"),
        sa.ForeignKeyConstraint(
            ["organization_id", "deployment_id", "deployment_revision"],
            [
                "bot_model_deployments.organization_id",
                "bot_model_deployments.deployment_id",
                "bot_model_deployments.revision",
            ],
            name="fk_bot_profile_deployment_revision",
        ),
        sa.CheckConstraint("version >= 1", name="ck_bot_profile_version_positive"),
        sa.CheckConstraint(
            "concurrency_limit >= 1", name="ck_bot_profile_concurrency_positive"
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_bot_profile_fingerprint_length"
        ),
    )
    for table in TENANT_TABLES:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    op.create_index(
        "ix_bot_profiles_agent_identity", "bot_profiles", ["agent_identity"]
    )
    _enable_rls()


def downgrade() -> None:
    _require_empty_tables()
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("bot_profiles")
    op.drop_table("bot_model_deployments")
    op.drop_table("bot_provider_connections")


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    predicate = (
        "organization_id = nullif(current_setting('dor.organization_id', true), '')"
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def _require_empty_tables() -> None:
    bind = op.get_bind()
    for table in reversed(TENANT_TABLES):
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            raise RuntimeError(
                f"cannot downgrade: {table} contains {count} rows; archive it first"
            )
