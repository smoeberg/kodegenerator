"""Add tenant-scoped immutable multi-spec artifact acceptances.

Revision ID: 030_artifact_acceptances
Revises: 029_requirement_traceability
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "030_artifact_acceptances"
down_revision = "029_requirement_traceability"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "artifact_acceptances",
        sa.Column("acceptance_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("repository", sa.String(512), nullable=False),
        sa.Column("artifact_set_fingerprint", sa.String(64), nullable=False),
        sa.Column("bundle_fingerprint", sa.String(64), nullable=False),
        sa.Column("contract_id", sa.String(128), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("contract_fingerprint", sa.String(64), nullable=False),
        sa.Column("command_id", sa.String(128), nullable=False),
        sa.Column("accepted_by", sa.String(128), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.String(2000), nullable=False, server_default=""),
        sa.Column("manifest_ids", sa.JSON(), nullable=False),
        sa.Column("specs_payload", sa.JSON(), nullable=False),
        sa.Column("acceptance_payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("acceptance_id"),
        sa.UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_artifact_acceptance_command",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "bundle_fingerprint",
            "contract_fingerprint",
            name="uq_artifact_acceptance_bundle_contract",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "accepted_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_artifact_acceptance_actor_org",
        ),
    )
    op.create_index(
        "ix_artifact_acceptances_organization_id",
        "artifact_acceptances",
        ["organization_id"],
    )
    op.create_index(
        "ix_artifact_acceptances_repository",
        "artifact_acceptances",
        ["repository"],
    )
    op.create_index(
        "ix_artifact_acceptances_artifact_set_fingerprint",
        "artifact_acceptances",
        ["artifact_set_fingerprint"],
    )
    op.create_index(
        "ix_artifact_acceptances_bundle_fingerprint",
        "artifact_acceptances",
        ["bundle_fingerprint"],
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "artifact_acceptances" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "artifact_acceptances" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "artifact_acceptances" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "artifact_acceptances"')).scalar_one():
        raise RuntimeError("cannot downgrade: artifact_acceptances contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "artifact_acceptances"')
        op.execute('ALTER TABLE "artifact_acceptances" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "artifact_acceptances" DISABLE ROW LEVEL SECURITY')
    op.drop_index(
        "ix_artifact_acceptances_bundle_fingerprint",
        table_name="artifact_acceptances",
    )
    op.drop_index(
        "ix_artifact_acceptances_artifact_set_fingerprint",
        table_name="artifact_acceptances",
    )
    op.drop_index(
        "ix_artifact_acceptances_repository",
        table_name="artifact_acceptances",
    )
    op.drop_index(
        "ix_artifact_acceptances_organization_id",
        table_name="artifact_acceptances",
    )
    op.drop_table("artifact_acceptances")
