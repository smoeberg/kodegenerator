"""Make role definitions organization-owned and enforce assignment integrity.

Revision ID: 005_authority_org_scope
Revises: 004_event_org_sequence
"""
from alembic import op
import sqlalchemy as sa

revision = "005_authority_org_scope"
down_revision = "004_event_org_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "role_definitions",
        sa.Column("organization_id", sa.String(length=128), nullable=True),
    )
    bind = op.get_bind()

    ambiguous = bind.execute(
        sa.text(
            """
            SELECT role_definition_id
            FROM role_assignments
            GROUP BY role_definition_id
            HAVING COUNT(DISTINCT organization_id) > 1
            """
        )
    ).fetchall()
    if ambiguous:
        ids = ", ".join(row[0] for row in ambiguous)
        raise RuntimeError(
            "Cannot scope role definitions automatically; roles are assigned "
            f"across multiple organizations: {ids}"
        )

    bind.execute(
        sa.text(
            """
            UPDATE role_definitions
            SET organization_id = (
                SELECT ra.organization_id
                FROM role_assignments AS ra
                WHERE ra.role_definition_id = role_definitions.id
                LIMIT 1
            )
            """
        )
    )

    unscoped = bind.execute(
        sa.text("SELECT id FROM role_definitions WHERE organization_id IS NULL")
    ).fetchall()
    if unscoped:
        ids = ", ".join(row[0] for row in unscoped)
        raise RuntimeError(
            "Cannot scope unassigned role definitions automatically: " + ids
        )

    with op.batch_alter_table("role_definitions") as batch_op:
        batch_op.alter_column(
            "organization_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_role_definition_org_id",
            ["organization_id", "id"],
        )

    with op.batch_alter_table("role_assignments") as batch_op:
        batch_op.create_foreign_key(
            "fk_role_assignment_actor_org",
            "actors",
            ["actor_id", "organization_id"],
            ["id", "organization_id"],
        )
        batch_op.create_foreign_key(
            "fk_role_assignment_role_org",
            "role_definitions",
            ["organization_id", "role_definition_id"],
            ["organization_id", "id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("role_assignments") as batch_op:
        batch_op.drop_constraint("fk_role_assignment_role_org", type_="foreignkey")
        batch_op.drop_constraint("fk_role_assignment_actor_org", type_="foreignkey")

    with op.batch_alter_table("role_definitions") as batch_op:
        batch_op.drop_constraint("uq_role_definition_org_id", type_="unique")

    op.drop_column("role_definitions", "organization_id")
