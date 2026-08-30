"""Add mandatory tenant scope and RLS to queue and execution replay.

Revision ID: 017_queue_replay_tenant_scope
Revises: 016_extended_tenant_rls
"""

import sqlalchemy as sa
from alembic import op


revision = "017_queue_replay_tenant_scope"
down_revision = "016_extended_tenant_rls"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "runtime_queue_messages",
    "execution_replay_ledger",
)
POLICY_NAME = "dor_tenant_isolation"


def upgrade() -> None:
    """Rebuild only empty legacy tables; never invent tenant ownership."""
    _require_empty_tables("upgrade")
    op.drop_table("execution_replay_ledger")
    op.drop_table("runtime_queue_messages")
    _create_scoped_queue()
    _create_scoped_replay_ledger()

    if op.get_bind().dialect.name != "postgresql":
        return
    predicate = (
        "organization_id = "
        "nullif(current_setting('dor.organization_id', true), '')"
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    """Restore the legacy schema only after explicitly draining both tables."""
    _require_empty_tables("downgrade")
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("execution_replay_ledger")
    op.drop_table("runtime_queue_messages")
    _create_legacy_queue()
    _create_legacy_replay_ledger()


def _require_empty_tables(operation: str) -> None:
    bind = op.get_bind()
    for table in TENANT_TABLES:
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            raise RuntimeError(
                f"cannot {operation}: {table} contains {count} rows; "
                "drain or explicitly archive them first"
            )


def _create_scoped_queue() -> None:
    op.create_table(
        "runtime_queue_messages",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        *_queue_columns(),
        sa.PrimaryKeyConstraint("organization_id", "id"),
    )
    _queue_indexes(include_organization=True)


def _create_legacy_queue() -> None:
    op.create_table(
        "runtime_queue_messages",
        sa.Column("id", sa.String(length=128), nullable=False),
        *_queue_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    _queue_indexes(include_organization=False)


def _queue_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.String(length=64), nullable=True),
    )


def _queue_indexes(*, include_organization: bool) -> None:
    columns = ("topic", "status", "available_at", "worker_id", "lease_id")
    for column in columns:
        op.create_index(
            f"ix_runtime_queue_messages_{column}",
            "runtime_queue_messages",
            [column],
        )
    if include_organization:
        op.create_index(
            "ix_runtime_queue_messages_organization_id",
            "runtime_queue_messages",
            ["organization_id"],
        )


def _create_scoped_replay_ledger() -> None:
    op.create_table(
        "execution_replay_ledger",
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        *_replay_columns(),
        sa.PrimaryKeyConstraint("organization_id", "execution_id"),
    )
    _replay_indexes(include_organization=True)


def _create_legacy_replay_ledger() -> None:
    op.create_table(
        "execution_replay_ledger",
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        *_replay_columns(),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    _replay_indexes(include_organization=False)


def _replay_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("grant_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.String(length=64), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
    )


def _replay_indexes(*, include_organization: bool) -> None:
    columns = ("status", "lease_expires_at", "request_id", "grant_id")
    for column in columns:
        op.create_index(
            f"ix_execution_replay_ledger_{column}",
            "execution_replay_ledger",
            [column],
        )
    if include_organization:
        op.create_index(
            "ix_execution_replay_ledger_organization_id",
            "execution_replay_ledger",
            ["organization_id"],
        )
