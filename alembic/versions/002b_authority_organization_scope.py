"""Backfill the Phase 3 role definition organization boundary.

Revision ID: 002b_authority_organization_scope
Revises: 002_phase3_authority

The original authority migration created role_definitions without the mandatory
organization_id column even though role assignments already referenced it.
This migration repairs the schema before P3-14 execution receipts are added.
Existing rows with no organization mapping fail closed rather than being
silently assigned to an arbitrary organization.
"""
from alembic import op
import sqlalchemy as sa

revision = "002b_authority_organization_scope"
down_revision = "002_phase3_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("role_definitions", recreate="always") as batch:
        batch.add_column(
            sa.Column("organization_id", sa.String(length=128), nullable=False)
        )
        batch.create_index(
            "ix_role_definitions_organization_id",
            ["organization_id"],
        )
        batch.create_unique_constraint(
            "uq_role_definition_org_id",
            ["organization_id", "id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("role_definitions", recreate="always") as batch:
        batch.drop_constraint("uq_role_definition_org_id", type_="unique")
        batch.drop_index("ix_role_definitions_organization_id")
        batch.drop_column("organization_id")
