"""merge phase2 and phase3 heads

Revision ID: 003_merge_heads
Revises: ("002_phase2_commands", "002_phase3_authority")
Create Date: 2026-08-06 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "003_merge_heads"
down_revision = ("002_phase2_commands", "002_phase3_authority")
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
