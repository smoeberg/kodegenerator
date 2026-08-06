"""Scope domain-event sequence uniqueness by organization.

Revision ID: 004_event_org_sequence
Revises: 003_merge_heads
"""
from alembic import op

revision = "004_event_org_sequence"
down_revision = "003_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("domain_events") as batch_op:
        batch_op.drop_constraint("uq_event_aggregate_sequence", type_="unique")
        batch_op.create_unique_constraint(
            "uq_event_aggregate_org_sequence",
            ["aggregate_id", "organization_id", "sequence"],
        )


def downgrade() -> None:
    with op.batch_alter_table("domain_events") as batch_op:
        batch_op.drop_constraint("uq_event_aggregate_org_sequence", type_="unique")
        batch_op.create_unique_constraint(
            "uq_event_aggregate_sequence",
            ["aggregate_id", "sequence"],
        )
