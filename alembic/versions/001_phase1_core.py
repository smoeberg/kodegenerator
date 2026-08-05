"""Phase 1 core runtime schema.

Revision ID: 001_phase1_core
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "001_phase1_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "actors",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("identity", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_actor_org_id"),
    )
    op.create_index("ix_actors_organization_id", "actors", ["organization_id"])
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_state", sa.String(length=64), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflows_organization_id", "workflows", ["organization_id"])
    op.create_table(
        "domain_events",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=True),
        sa.Column("aggregate_type", sa.String(length=128), nullable=True),
        sa.Column("organization_id", sa.String(length=128), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id", "sequence", name="uq_event_aggregate_sequence"),
    )
    op.create_index("ix_domain_events_event_type", "domain_events", ["event_type"])
    op.create_index("ix_domain_events_aggregate_id", "domain_events", ["aggregate_id"])
    op.create_index("ix_domain_events_organization_id", "domain_events", ["organization_id"])
    op.create_index("ix_domain_events_timestamp", "domain_events", ["timestamp"])
    op.create_index("ix_domain_events_correlation_id", "domain_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_domain_events_correlation_id", table_name="domain_events")
    op.drop_index("ix_domain_events_timestamp", table_name="domain_events")
    op.drop_index("ix_domain_events_organization_id", table_name="domain_events")
    op.drop_index("ix_domain_events_aggregate_id", table_name="domain_events")
    op.drop_index("ix_domain_events_event_type", table_name="domain_events")
    op.drop_table("domain_events")
    op.drop_index("ix_workflows_organization_id", table_name="workflows")
    op.drop_table("workflows")
    op.drop_index("ix_actors_organization_id", table_name="actors")
    op.drop_table("actors")
    op.drop_table("organizations")
