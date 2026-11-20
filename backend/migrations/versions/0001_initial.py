"""initial schema: sources, articles (with full-text search), ingestion_runs

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("homepage", sa.Text),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("adapter", sa.String(64)),
        sa.Column("poll_minutes", sa.Integer, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("show_excerpt", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("language", sa.String(16)),
        sa.Column("options", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("in_registry", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_polled_at", TS),
        sa.Column("last_success_at", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("last_item_count", sa.Integer),
        sa.Column("etag", sa.Text),
        sa.Column("last_modified", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sources_category", "sources", ["category"])

    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("image_url", sa.Text),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("published_at", TS, nullable=False),
        sa.Column("published_estimated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("language", sa.String(16)),
        sa.Column("title_fp", sa.String(40)),
        sa.Column("fetched_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('simple'::regconfig, coalesce(summary, '')), 'B')",
                persisted=True,
            ),
        ),
        sa.UniqueConstraint("source_id", "external_id", name="uq_articles_source_external"),
        sa.UniqueConstraint("url_hash", name="uq_articles_url_hash"),
    )
    op.create_index("ix_articles_published", "articles", [sa.text("published_at DESC"), sa.text("id DESC")])
    op.create_index(
        "ix_articles_category_published",
        "articles",
        ["category", sa.text("published_at DESC"), sa.text("id DESC")],
    )
    op.create_index("ix_articles_source_published", "articles", ["source_id", sa.text("published_at DESC")])
    op.create_index("ix_articles_title_fp", "articles", ["title_fp", "published_at"])
    op.create_index("ix_articles_search", "articles", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("not_modified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("items_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_runs_source_started", "ingestion_runs", ["source_id", sa.text("started_at DESC")])


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("articles")
    op.drop_table("sources")
