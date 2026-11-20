"""sources.origin: 'registry' (sources.yaml) or 'bot' (added by an admin via the Telegram bot)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("origin", sa.String(16), nullable=False, server_default="registry"))
    op.add_column("sources", sa.Column("added_by", sa.BigInteger, nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "added_by")
    op.drop_column("sources", "origin")
