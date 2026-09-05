"""Add durable tenant-scoped onboarding intent history.

Revision ID: 026_onboarding_intents
Revises: 025_swarm_control_state
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "026_onboarding_intents"
down_revision = "025_swarm_control_state"
branch_labels = None
depends_on = None
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "onboarding_intents",
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("source_repository", sa.String(1024), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("target_stack", sa.JSON(), nullable=True),
        sa.Column("supersedes_intent_id", sa.String(64), nullable=True),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("declared_by", sa.String(128), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.UniqueConstraint(
            "organization_id",
            "intent_id",
            name="uq_onboarding_intent_org_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "supersedes_intent_id",
            name="uq_onboarding_intent_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "declared_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_onboarding_intent_actor_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "supersedes_intent_id"],
            ["onboarding_intents.organization_id", "onboarding_intents.intent_id"],
            name="fk_onboarding_intent_supersedes_org",
        ),
    )
    op.create_index(
        "ix_onboarding_intents_organization_id",
        "onboarding_intents",
        ["organization_id"],
    )
    op.create_index(
        "ix_onboarding_intents_source_repository",
        "onboarding_intents",
        ["source_repository"],
    )
    op.create_index(
        "uq_onboarding_intent_root_repository",
        "onboarding_intents",
        ["organization_id", "source_repository"],
        unique=True,
        postgresql_where=sa.text("supersedes_intent_id IS NULL"),
        sqlite_where=sa.text("supersedes_intent_id IS NULL"),
    )

    if op.get_bind().dialect.name == "postgresql":
        predicate = (
            "organization_id = nullif(current_setting('dor.organization_id', true), '')"
        )
        op.execute('ALTER TABLE "onboarding_intents" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "onboarding_intents" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "onboarding_intents" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM "onboarding_intents"')).scalar_one():
        raise RuntimeError("cannot downgrade: onboarding_intents contains rows")
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "onboarding_intents"')
        op.execute('ALTER TABLE "onboarding_intents" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "onboarding_intents" DISABLE ROW LEVEL SECURITY')
    op.drop_index(
        "uq_onboarding_intent_root_repository",
        table_name="onboarding_intents",
    )
    op.drop_index(
        "ix_onboarding_intents_source_repository",
        table_name="onboarding_intents",
    )
    op.drop_index(
        "ix_onboarding_intents_organization_id",
        table_name="onboarding_intents",
    )
    op.drop_table("onboarding_intents")
