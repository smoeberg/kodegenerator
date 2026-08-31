"""Add append-only bot evaluation and performance ledgers.

Revision ID: 021_bot_evaluation_performance
Revises: 020_bot_selection_assignments
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "021_bot_evaluation_performance"
down_revision = "020_bot_selection_assignments"
branch_labels = None
depends_on = None

TABLES = (
    "evaluation_rubrics",
    "evaluation_records",
    "bot_performance_observations",
    "bot_performance_snapshots",
)
POLICY = "dor_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "evaluation_rubrics",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("rubric_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subject_classes", sa.JSON(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("pass_threshold", sa.Float(), nullable=False),
        sa.Column("independence_level", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "rubric_id", "version"),
        sa.CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 1",
            name="ck_evaluation_rubric_threshold",
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name="ck_evaluation_rubric_fingerprint"
        ),
    )
    op.create_table(
        "evaluation_records",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("evaluation_id", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("subject_class", sa.String(128), nullable=False),
        sa.Column("subject_fingerprint", sa.String(64), nullable=False),
        sa.Column("rubric_id", sa.String(128), nullable=False),
        sa.Column("rubric_version", sa.Integer(), nullable=False),
        sa.Column("rubric_fingerprint", sa.String(64), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("producer", sa.JSON(), nullable=False),
        sa.Column("evaluator", sa.JSON()),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("semantic_evidence", sa.JSON(), nullable=False),
        sa.Column("hard_failures", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "evaluation_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "rubric_id", "rubric_version"],
            [
                "evaluation_rubrics.organization_id",
                "evaluation_rubrics.rubric_id",
                "evaluation_rubrics.version",
            ],
            name="fk_evaluation_record_rubric",
        ),
        sa.CheckConstraint(
            "outcome IN ('pass', 'fail', 'rework')", name="ck_evaluation_outcome"
        ),
    )
    op.create_table(
        "bot_performance_observations",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("bot_profile_id", sa.String(128), nullable=False),
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("task_context", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("rubric_id", sa.String(128), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("ledger_position", sa.Integer(), nullable=False),
        sa.Column("supersedes_observation_id", sa.String(64)),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "observation_id"),
        sa.UniqueConstraint(
            "organization_id", "ledger_position", name="uq_performance_ledger_position"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "supersedes_observation_id"],
            [
                "bot_performance_observations.organization_id",
                "bot_performance_observations.observation_id",
            ],
            name="fk_performance_observation_supersedes",
        ),
    )
    op.create_table(
        "bot_performance_snapshots",
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("bot_profile_id", sa.String(128), nullable=False),
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("task_context", sa.Text(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("definitions", sa.JSON(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("decay_version", sa.String(64), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("ledger_position", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "snapshot_id"),
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
