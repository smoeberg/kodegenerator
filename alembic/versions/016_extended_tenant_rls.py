"""Extend tenant RLS to Pipeline and Council persistence.

Revision ID: 016_extended_tenant_rls
Revises: 015_core_tenant_rls
"""

from alembic import op


revision = "016_extended_tenant_rls"
down_revision = "015_core_tenant_rls"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "pipeline_runtime_states",
    "governed_llm_calls",
    "terminal_side_effects",
    "council_sessions",
    "council_disputes",
    "council_votes",
    "council_evidence_bindings",
    "council_failure_observations",
    "council_outbox_events",
)
POLICY_NAME = "dor_tenant_isolation"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    predicate = (
        "organization_id = "
        "nullif(current_setting('dor.organization_id', true), '')"
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
