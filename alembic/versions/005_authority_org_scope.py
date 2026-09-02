"""Make role definitions organization-owned and enforce assignment integrity.

Revision ID: 005_authority_org_scope
Revises: 004_event_org_sequence
"""

import sqlalchemy as sa

from alembic import op

revision = "005_authority_org_scope"
down_revision = "004_event_org_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("role_definitions")}
    column_added = "organization_id" not in columns
    if column_added:
        op.add_column(
            "role_definitions",
            sa.Column("organization_id", sa.String(length=128), nullable=True),
        )

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

    if column_added:
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
    else:
        mismatched = bind.execute(
            sa.text(
                """
                SELECT DISTINCT rd.id
                FROM role_definitions AS rd
                JOIN role_assignments AS ra ON ra.role_definition_id = rd.id
                WHERE rd.organization_id <> ra.organization_id
                """
            )
        ).fetchall()
        if mismatched:
            ids = ", ".join(row[0] for row in mismatched)
            raise RuntimeError(
                "Existing role definition organization scope conflicts with "
                f"role assignments: {ids}"
            )

    unscoped = bind.execute(
        sa.text("SELECT id FROM role_definitions WHERE organization_id IS NULL")
    ).fetchall()
    if unscoped:
        ids = ", ".join(row[0] for row in unscoped)
        raise RuntimeError(
            "Cannot scope unassigned role definitions automatically: " + ids
        )

    unique_constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("role_definitions")
    }
    with op.batch_alter_table("role_definitions") as batch_op:
        if column_added:
            batch_op.alter_column(
                "organization_id",
                existing_type=sa.String(length=128),
                nullable=False,
            )
        if "uq_role_definition_org_id" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_role_definition_org_id",
                ["organization_id", "id"],
            )

    foreign_keys = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_foreign_keys("role_assignments")
    }
    with op.batch_alter_table("role_assignments") as batch_op:
        if "fk_role_assignment_actor_org" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_role_assignment_actor_org",
                "actors",
                ["actor_id", "organization_id"],
                ["id", "organization_id"],
            )
        if "fk_role_assignment_role_org" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_role_assignment_role_org",
                "role_definitions",
                ["organization_id", "role_definition_id"],
                ["organization_id", "id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("role_assignments")
    }
    with op.batch_alter_table("role_assignments") as batch_op:
        if "fk_role_assignment_role_org" in foreign_keys:
            batch_op.drop_constraint("fk_role_assignment_role_org", type_="foreignkey")
        if "fk_role_assignment_actor_org" in foreign_keys:
            batch_op.drop_constraint("fk_role_assignment_actor_org", type_="foreignkey")

    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("role_definitions")}
    if "organization_id" not in columns:
        return
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("role_definitions")
    }
    if "uq_role_definition_org_id" in unique_constraints:
        with op.batch_alter_table("role_definitions") as batch_op:
            batch_op.drop_constraint("uq_role_definition_org_id", type_="unique")

    op.drop_column("role_definitions", "organization_id")
