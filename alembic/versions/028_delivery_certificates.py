"""Add authoritative tenant-scoped delivery certificates.

Revision ID: 028_delivery_certificates
Revises: 027_organization_memberships
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028_delivery_certificates"
down_revision = "027_organization_memberships"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "delivery_certificates",
        sa.Column("certificate_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("contract_id", sa.String(128), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("contract_fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("command_id", sa.String(128), nullable=False),
        sa.Column("certified_by", sa.String(128), nullable=False),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("candidate_payload", sa.JSON(), nullable=False),
        sa.Column("certificate_payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("certificate_id"),
        sa.UniqueConstraint(
            "organization_id",
            "candidate_id",
            "contract_fingerprint",
            name="uq_delivery_certificate_candidate_contract",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_delivery_certificate_command",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "certified_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_delivery_certificate_actor_org",
        ),
    )
    op.create_index(
        "ix_delivery_certificates_organization_id",
        "delivery_certificates",
        ["organization_id"],
    )
    op.create_index(
        "ix_delivery_certificates_candidate_id",
        "delivery_certificates",
        ["candidate_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "delivery_certificates" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "delivery_certificates" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "delivery_certificates" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "delivery_certificates"')).scalar_one():
        raise RuntimeError("cannot downgrade: delivery_certificates contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "delivery_certificates"')
        op.execute('ALTER TABLE "delivery_certificates" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "delivery_certificates" DISABLE ROW LEVEL SECURITY')
    op.drop_index(
        "ix_delivery_certificates_candidate_id",
        table_name="delivery_certificates",
    )
    op.drop_index(
        "ix_delivery_certificates_organization_id",
        table_name="delivery_certificates",
    )
    op.drop_table("delivery_certificates")
