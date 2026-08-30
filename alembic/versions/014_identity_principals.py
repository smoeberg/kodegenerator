"""Add persistent authentication principals.

Revision ID: 014_identity_principals
Revises: 013_terminal_side_effects
"""

from alembic import op
import sqlalchemy as sa

revision = "014_identity_principals"
down_revision = "013_terminal_side_effects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_principals",
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("username"),
    )


def downgrade() -> None:
    op.drop_table("identity_principals")
