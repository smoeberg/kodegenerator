"""Add governed factory integration plans and receipts.

Revision ID: 023_factory_integration
Revises: 022_factory_work_candidates
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "023_factory_integration"
down_revision = "022_factory_work_candidates"
branch_labels = None
depends_on = None
TABLES = ("factory_integration_plans", "factory_integration_receipts")
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "factory_integration_plans",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "plan_id"),
        sa.UniqueConstraint(
            "organization_id",
            "workflow_id",
            "fingerprint",
            name="uq_factory_integration_plan",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_factory_integration_idempotency",
        ),
    )
    op.create_table(
        "factory_integration_receipts",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("receipt_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "receipt_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            [
                "factory_integration_plans.organization_id",
                "factory_integration_plans.plan_id",
            ],
            name="fk_factory_integration_receipt_plan",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "plan_fingerprint",
            name="uq_factory_successful_integration",
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
