"""sources.admin_disabled: a source switched off by an admin in the bot stays off
across registry syncs (sources.yaml would otherwise re-enable it)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("admin_disabled", sa.Boolean, nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("sources", "admin_disabled")
