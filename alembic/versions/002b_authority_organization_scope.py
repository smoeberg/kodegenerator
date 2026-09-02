"""Backfill the Phase 3 role definition organization boundary.

Revision ID: 002b_authority_organization_scope
Revises: 002_phase3_authority

The original authority migration created role_definitions without the mandatory
organization_id column even though role assignments already referenced it.
This migration repairs the schema before P3-14 execution receipts are added.
Existing rows with no organization mapping fail closed rather than being
silently assigned to an arbitrary organization.
"""

import sqlalchemy as sa

from alembic import op

revision = "002b_authority_organization_scope"
down_revision = "002_phase3_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("role_definitions")}
    if "organization_id" in columns:
        indexes = {index["name"] for index in inspector.get_indexes("role_definitions")}
        if "ix_role_definitions_organization_id" not in indexes:
            op.create_index(
                "ix_role_definitions_organization_id",
                "role_definitions",
                ["organization_id"],
            )
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("role_definitions")
        }
        if "uq_role_definition_org_id" not in unique_constraints:
            with op.batch_alter_table("role_definitions") as batch:
                batch.create_unique_constraint(
                    "uq_role_definition_org_id",
                    ["organization_id", "id"],
                )
        return

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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("role_definitions")}
    if "organization_id" not in columns:
        return
    foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("role_assignments")
    }
    indexes = {index["name"] for index in inspector.get_indexes("role_definitions")}
    if "fk_role_assignment_role_org" in foreign_keys:
        if "ix_role_definitions_organization_id" in indexes:
            op.drop_index(
                "ix_role_definitions_organization_id",
                table_name="role_definitions",
            )
        return

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("role_definitions")
    }
    with op.batch_alter_table("role_definitions", recreate="always") as batch:
        if "uq_role_definition_org_id" in unique_constraints:
            batch.drop_constraint("uq_role_definition_org_id", type_="unique")
        if "ix_role_definitions_organization_id" in indexes:
            batch.drop_index("ix_role_definitions_organization_id")
        batch.drop_column("organization_id")
