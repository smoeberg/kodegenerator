"""Add durable pipeline state and governed LLM replay.

Revision ID: 012_pipeline_persistence
Revises: 011_council_runtime
"""

import sqlalchemy as sa

from alembic import op

revision = "012_pipeline_persistence"
down_revision = "011_council_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runtime_states",
        sa.Column("store_id", sa.String(length=128), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), primary_key=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pipeline_runtime_states_organization_id",
        "pipeline_runtime_states",
        ["organization_id"],
    )
    op.create_table(
        "governed_llm_calls",
        sa.Column("organization_id", sa.String(length=128), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=255), primary_key=True),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.String(length=64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("failure_class", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_governed_llm_calls_status", "governed_llm_calls", ["status"])
    op.create_index(
        "ix_governed_llm_calls_lease_expires_at",
        "governed_llm_calls",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governed_llm_calls_lease_expires_at", table_name="governed_llm_calls"
    )
    op.drop_index("ix_governed_llm_calls_status", table_name="governed_llm_calls")
    op.drop_table("governed_llm_calls")
    op.drop_index(
        "ix_pipeline_runtime_states_organization_id",
        table_name="pipeline_runtime_states",
    )
    op.drop_table("pipeline_runtime_states")
