"""Bind onboarding intents to Control Plane projects (SC-101A).

Revision ID: 033_onboarding_project_identity
Revises: 032_work_unit_revisions
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033_onboarding_project_identity"
down_revision = "032_work_unit_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_intents",
        sa.Column("project_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_onboarding_intents_project_id",
        "onboarding_intents",
        ["project_id"],
    )
    op.drop_index(
        "uq_onboarding_intent_root_repository",
        table_name="onboarding_intents",
    )
    op.create_index(
        "uq_onboarding_intent_root_project_repository",
        "onboarding_intents",
        ["organization_id", "project_id", "source_repository"],
        unique=True,
        postgresql_where=sa.text(
            "supersedes_intent_id IS NULL AND project_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "supersedes_intent_id IS NULL AND project_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_onboarding_intent_legacy_root_repository",
        "onboarding_intents",
        ["organization_id", "source_repository"],
        unique=True,
        postgresql_where=sa.text(
            "supersedes_intent_id IS NULL AND project_id IS NULL"
        ),
        sqlite_where=sa.text(
            "supersedes_intent_id IS NULL AND project_id IS NULL"
        ),
    )
    with op.batch_alter_table("onboarding_intents") as batch:
        batch.create_foreign_key(
            "fk_onboarding_intent_project_org",
            "projects",
            ["organization_id", "project_id"],
            ["organization_id", "id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bound = bind.execute(
        sa.text(
            'SELECT COUNT(*) FROM "onboarding_intents" WHERE project_id IS NOT NULL'
        )
    ).scalar_one()
    if bound:
        raise RuntimeError(
            "cannot downgrade: project-bound onboarding intents would lose provenance"
        )
    with op.batch_alter_table("onboarding_intents") as batch:
        batch.drop_constraint(
            "fk_onboarding_intent_project_org",
            type_="foreignkey",
        )
    op.drop_index(
        "uq_onboarding_intent_legacy_root_repository",
        table_name="onboarding_intents",
    )
    op.drop_index(
        "uq_onboarding_intent_root_project_repository",
        table_name="onboarding_intents",
    )
    op.create_index(
        "uq_onboarding_intent_root_repository",
        "onboarding_intents",
        ["organization_id", "source_repository"],
        unique=True,
        postgresql_where=sa.text("supersedes_intent_id IS NULL"),
        sqlite_where=sa.text("supersedes_intent_id IS NULL"),
    )
    op.drop_index(
        "ix_onboarding_intents_project_id",
        table_name="onboarding_intents",
    )
    op.drop_column("onboarding_intents", "project_id")
