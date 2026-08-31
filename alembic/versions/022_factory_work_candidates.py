"""Add factory work packages and immutable candidate evidence.

Revision ID: 022_factory_work_candidates
Revises: 021_bot_evaluation_performance
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "022_factory_work_candidates"
down_revision = "021_bot_evaluation_performance"
branch_labels = None
depends_on = None
TABLES = (
    "factory_work_packages",
    "factory_candidate_deliveries",
    "factory_candidate_selections",
)
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "factory_work_packages",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("work_package_id", sa.String(64), nullable=False),
        sa.Column("logical_task_id", sa.String(128), nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "work_package_id"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_factory_package_idempotency"
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_factory_package_fingerprint"
        ),
    )
    op.create_table(
        "factory_candidate_deliveries",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("candidate_id", sa.String(128), nullable=False),
        sa.Column("work_package_id", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(128), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "candidate_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "work_package_id"],
            [
                "factory_work_packages.organization_id",
                "factory_work_packages.work_package_id",
            ],
            name="fk_factory_candidate_package",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            "head_sha",
            name="uq_factory_candidate_execution_head",
        ),
    )
    op.create_table(
        "factory_candidate_selections",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("selection_id", sa.String(64), nullable=False),
        sa.Column("logical_task_id", sa.String(128), nullable=False),
        sa.Column("work_package_fingerprint", sa.String(64), nullable=False),
        sa.Column("winner_candidate_id", sa.String(128)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "selection_id"),
    )
    op.create_index(
        "uq_factory_candidate_winner",
        "factory_candidate_selections",
        ["organization_id", "logical_task_id", "work_package_fingerprint"],
        unique=True,
        postgresql_where=sa.text("winner_candidate_id IS NOT NULL"),
        sqlite_where=sa.text("winner_candidate_id IS NOT NULL"),
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
