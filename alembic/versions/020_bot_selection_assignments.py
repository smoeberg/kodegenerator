"""Add frozen Council selections and decision receipts.

Revision ID: 020_bot_selection_assignments
Revises: 019_council_configuration
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "020_bot_selection_assignments"
down_revision = "019_council_configuration"
branch_labels = None
depends_on = None

TABLES = (
    "bot_selection_decisions",
    "bot_session_assignments",
)
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "bot_selection_decisions",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("template_fingerprint", sa.String(64), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("selector_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("receipts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "decision_id"),
        sa.UniqueConstraint(
            "organization_id", "run_id", name="uq_bot_selection_run"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "template_id", "template_version"],
            [
                "council_templates.organization_id",
                "council_templates.template_id",
                "council_templates.version",
            ],
            name="fk_council_selection_template_version",
        ),
        sa.CheckConstraint(
            "length(template_fingerprint) = 64",
            name="ck_council_selection_template_fingerprint",
        ),
        sa.CheckConstraint(
            "length(context_fingerprint) = 64",
            name="ck_council_selection_context_fingerprint",
        ),
        sa.CheckConstraint(
            "length(decision_id) = 64",
            name="ck_bot_selection_decision_id",
        ),
        sa.CheckConstraint(
            "status IN ('selected', 'blocked')",
            name="ck_bot_selection_status",
        ),
    )
    op.create_table(
        "bot_session_assignments",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("assignment_id", sa.String(64), nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("assignment_index", sa.Integer(), nullable=False),
        sa.Column("stage_id", sa.String(128), nullable=False),
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("role_version", sa.Integer(), nullable=False),
        sa.Column("allocation_id", sa.String(128), nullable=False),
        sa.Column("allocation_version", sa.Integer(), nullable=False),
        sa.Column("bot_profile_id", sa.String(128), nullable=False),
        sa.Column("bot_profile_version", sa.Integer(), nullable=False),
        sa.Column("profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("agent_identity", sa.String(64), nullable=False),
        sa.Column("deployment_id", sa.String(128), nullable=False),
        sa.Column("deployment_revision", sa.Integer(), nullable=False),
        sa.Column("deployment_fingerprint", sa.String(64), nullable=False),
        sa.Column("connection_id", sa.String(128), nullable=False),
        sa.Column("connection_version", sa.Integer(), nullable=False),
        sa.Column("connection_fingerprint", sa.String(64), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "assignment_id"),
        sa.UniqueConstraint(
            "organization_id",
            "decision_id",
            "assignment_index",
            name="uq_council_assignment_order",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "decision_id"],
            [
                "bot_selection_decisions.organization_id",
                "bot_selection_decisions.decision_id",
            ],
            name="fk_council_assignment_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "role_id", "role_version"],
            [
                "council_role_configurations.organization_id",
                "council_role_configurations.role_id",
                "council_role_configurations.version",
            ],
            name="fk_council_assignment_role",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "allocation_id", "allocation_version"],
            [
                "council_role_allocations.organization_id",
                "council_role_allocations.allocation_id",
                "council_role_allocations.version",
            ],
            name="fk_council_assignment_allocation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "bot_profile_id", "bot_profile_version"],
            [
                "bot_profiles.organization_id",
                "bot_profiles.bot_profile_id",
                "bot_profiles.version",
            ],
            name="fk_council_assignment_profile",
        ),
    )
    for table in TABLES:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    _enable_rls()


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        if bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one():
            raise RuntimeError(f"cannot downgrade: {table} contains rows")
    if bind.dialect.name == "postgresql":
        for table in reversed(TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in reversed(TABLES):
        op.drop_table(table)


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    predicate = (
        "organization_id = nullif(current_setting('dor.organization_id', true), '')"
    )
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY}" ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
