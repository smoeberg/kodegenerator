"""Add multi-organization principal memberships.

Revision ID: 027_organization_memberships
Revises: 026_onboarding_intents
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "027_organization_memberships"
down_revision = "026_onboarding_intents"
branch_labels = None
depends_on = None


_SQLITE_NAMING = {
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _replace_actor_primary_key(columns: list[str]) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table(
            "actors",
            recreate="always",
            naming_convention=_SQLITE_NAMING,
        ) as batch_op:
            batch_op.drop_constraint("pk_actors", type_="primary")
            batch_op.create_primary_key("pk_actors", columns)
        return

    primary_key_name = "actors_pkey" if dialect == "postgresql" else "PRIMARY"
    op.drop_constraint(primary_key_name, "actors", type_="primary")
    op.create_primary_key(primary_key_name, "actors", columns)


def upgrade() -> None:
    """Allow one actor identity to belong to multiple organizations."""
    _replace_actor_primary_key(["id", "organization_id"])

    op.create_table(
        "organization_memberships",
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "username",
            "organization_id",
            name="pk_organization_memberships",
        ),
    )
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships",
        ["organization_id"],
    )

    memberships = sa.table(
        "organization_memberships",
        sa.column("username", sa.String(length=128)),
        sa.column("organization_id", sa.String(length=128)),
        sa.column("is_admin", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    principals = sa.table(
        "identity_principals",
        sa.column("username", sa.String(length=128)),
        sa.column("organization_id", sa.String(length=128)),
    )
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    existing = connection.execute(
        sa.select(principals.c.username, principals.c.organization_id).where(
            principals.c.organization_id.is_not(None)
        )
    ).all()
    if existing:
        op.bulk_insert(
            memberships,
            [
                {
                    "username": row.username,
                    "organization_id": row.organization_id,
                    "is_admin": True,
                    "created_at": now,
                    "updated_at": now,
                }
                for row in existing
            ],
        )


def downgrade() -> None:
    """Remove membership catalog and restore the legacy single-actor key."""
    op.drop_index(
        "ix_organization_memberships_organization_id",
        table_name="organization_memberships",
    )
    op.drop_table("organization_memberships")
    _replace_actor_primary_key(["id"])
