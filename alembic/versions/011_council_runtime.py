"""Add the durable organization-scoped Council runtime.

Revision ID: 011_council_runtime
Revises: 010_runtime_queue_fencing
"""

import sqlalchemy as sa

from alembic import op

revision = "011_council_runtime"
down_revision = "010_runtime_queue_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "council_sessions",
        sa.Column("session_id", sa.String(length=128), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_revision", sa.String(length=128), nullable=False),
        sa.Column("workspace_revision", sa.String(length=128), nullable=False),
        sa.Column("context_packet_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("approval_threshold", sa.Float(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "session_id", name="uq_council_session_org_id"
        ),
    )
    op.create_index(
        "ix_council_sessions_organization_id", "council_sessions", ["organization_id"]
    )
    op.create_index(
        "ix_council_sessions_hypothesis_id", "council_sessions", ["hypothesis_id"]
    )
    op.create_index("ix_council_sessions_state", "council_sessions", ["state"])

    op.create_table(
        "council_disputes",
        sa.Column("dispute_id", sa.String(length=128), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_dispute_org_session",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_council_disputes_organization_id", "council_disputes", ["organization_id"]
    )
    op.create_index(
        "ix_council_disputes_session_id", "council_disputes", ["session_id"]
    )
    op.create_index(
        "ix_council_disputes_hypothesis_id", "council_disputes", ["hypothesis_id"]
    )
    op.create_index("ix_council_disputes_status", "council_disputes", ["status"])

    op.create_table(
        "council_votes",
        sa.Column("vote_id", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_vote_org_session",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            "round_number",
            "agent_id",
            name="uq_council_vote_org_session_round_agent",
        ),
    )
    op.create_index(
        "ix_council_votes_organization_id", "council_votes", ["organization_id"]
    )
    op.create_index("ix_council_votes_session_id", "council_votes", ["session_id"])

    op.create_table(
        "council_evidence_bindings",
        sa.Column("binding_id", sa.String(length=64), primary_key=True),
        sa.Column("evidence_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_revision", sa.String(length=128), nullable=False),
        sa.Column("workspace_revision", sa.String(length=128), nullable=False),
        sa.Column("context_packet_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_evidence_org_session",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            "evidence_id",
            name="uq_council_evidence_org_session_id",
        ),
    )
    op.create_index(
        "ix_council_evidence_bindings_evidence_id",
        "council_evidence_bindings",
        ["evidence_id"],
    )
    op.create_index(
        "ix_council_evidence_bindings_organization_id",
        "council_evidence_bindings",
        ["organization_id"],
    )
    op.create_index(
        "ix_council_evidence_bindings_session_id",
        "council_evidence_bindings",
        ["session_id"],
    )

    op.create_table(
        "council_failure_observations",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=False),
        sa.Column("failure", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_failure_org_session",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id", "event_id", name="uq_council_failure_org_event"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            name="uq_council_failure_org_execution",
        ),
    )
    op.create_index(
        "ix_council_failure_observations_organization_id",
        "council_failure_observations",
        ["organization_id"],
    )
    op.create_index(
        "ix_council_failure_observations_session_id",
        "council_failure_observations",
        ["session_id"],
    )
    op.create_index(
        "ix_council_failure_observations_hypothesis_id",
        "council_failure_observations",
        ["hypothesis_id"],
    )
    op.create_index(
        "ix_council_failure_observations_execution_id",
        "council_failure_observations",
        ["execution_id"],
    )
    op.create_index(
        "ix_council_failure_observations_fingerprint_hash",
        "council_failure_observations",
        ["fingerprint_hash"],
    )

    op.create_table(
        "council_outbox_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_council_outbox_events_organization_id",
        "council_outbox_events",
        ["organization_id"],
    )
    op.create_index(
        "ix_council_outbox_events_event_type", "council_outbox_events", ["event_type"]
    )
    op.create_index(
        "ix_council_outbox_events_aggregate_id",
        "council_outbox_events",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_council_outbox_events_correlation_id",
        "council_outbox_events",
        ["correlation_id"],
    )
    op.create_index(
        "ix_council_outbox_events_status", "council_outbox_events", ["status"]
    )


def downgrade() -> None:
    op.drop_table("council_outbox_events")
    op.drop_table("council_failure_observations")
    op.drop_table("council_evidence_bindings")
    op.drop_table("council_votes")
    op.drop_table("council_disputes")
    op.drop_table("council_sessions")
