from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    homepage: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[str] = mapped_column(String(16))
    adapter: Mapped[str | None] = mapped_column(String(64))
    poll_minutes: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    show_excerpt: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    language: Mapped[str | None] = mapped_column(String(16))
    options: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    in_registry: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # 'registry' = defined in sources.yaml; 'bot' = added by an admin through the Telegram bot
    origin: Mapped[str] = mapped_column(String(16), default="registry", server_default="registry")
    added_by: Mapped[int | None] = mapped_column(BigInteger)  # Telegram user id of the admin

    # operational status
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_item_count: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_articles_source_external"),
        UniqueConstraint("url_hash", name="uq_articles_url_hash"),
        Index("ix_articles_published", text("published_at DESC"), text("id DESC")),
        Index("ix_articles_category_published", "category", text("published_at DESC"), text("id DESC")),
        Index("ix_articles_source_published", "source_id", text("published_at DESC")),
        Index("ix_articles_title_fp", "title_fp", "published_at"),
        Index("ix_articles_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    language: Mapped[str | None] = mapped_column(String(16))
    title_fp: Mapped[str | None] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 'simple' config: no stemming/stop-words, so it works for any article language
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple'::regconfig, coalesce(summary, '')), 'B')",
            persisted=True,
        ),
        deferred=True,
    )


class IngestionRun(Base):
    """Per-source poll log, used for source-level error reporting."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_runs_source_started", "source_id", text("started_at DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean)
    not_modified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    items_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    items_inserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
