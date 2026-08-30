"""Enforce tenant isolation for the canonical runtime persistence core.

Revision ID: 015_core_tenant_rls
Revises: 014_identity_principals
"""

from alembic import op


revision = "015_core_tenant_rls"
down_revision = "014_identity_principals"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "actors",
    "role_definitions",
    "role_assignments",
    "workflows",
    "projects",
    "domain_events",
    "command_executions",
    "task_executions",
)
POLICY_NAME = "dor_tenant_isolation"


def upgrade() -> None:
    """Enable and force fail-closed RLS when the target is PostgreSQL."""
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
    """Remove only the policies introduced by this revision."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
