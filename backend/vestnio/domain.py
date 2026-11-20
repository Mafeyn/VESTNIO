"""Shared domain types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Category(StrEnum):
    GAMING = "gaming"
    WORLD = "world"
    TECHNOLOGY = "technology"

    @property
    def label(self) -> str:
        return {"gaming": "Gaming", "world": "World News", "technology": "Technology"}[self.value]


class IngestionMethod(StrEnum):
    RSS = "rss"  # RSS 2.0 / Atom / RDF via feedparser
    API = "api"  # official news API, handled by a named adapter
    HTML = "html"  # site-specific HTML parser (only where automated access is permitted)
    TELEGRAM = "telegram"  # public Telegram channel, via its t.me/s/<channel> web preview


class SourceStatus(StrEnum):
    PENDING = "pending"  # never fetched
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # recent failures, still retrying
    FAILING = "failing"  # many consecutive failures
    DISABLED = "disabled"  # turned off in config or missing credentials


class SourceConfig(BaseModel):
    """One entry of the source registry (sources.yaml)."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str
    url: HttpUrl
    homepage: HttpUrl | None = None
    category: Category
    method: IngestionMethod
    adapter: str | None = None  # required for api/html; defaults to "rss" for rss
    poll_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    enabled: bool = True
    # Publisher permits showing its excerpt next to the link (RSS/API teasers are
    # offered for exactly this). Set false to show headline + link only.
    show_excerpt: bool = True
    language: str | None = None  # fallback when the feed doesn't declare one
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("adapter")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v else v


@dataclass(slots=True)
class RawItem:
    """An article as extracted by a parser adapter, before normalization."""

    title: str | None
    url: str | None
    external_id: str | None = None
    summary: str | None = None
    image_url: str | None = None
    published: datetime | str | None = None
    language: str | None = None  # as declared by the feed/API; never translated
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedArticle:
    source_id: str
    category: Category
    external_id: str
    title: str
    summary: str | None
    image_url: str | None
    url: str
    canonical_url: str
    url_hash: str
    published_at: datetime
    published_estimated: bool  # True when the feed gave no timestamp and fetch time was used
    language: str | None = None  # BCP-47-ish code, e.g. "en", "en-gb"
    title_fp: str | None = None  # title fingerprint for fallback duplicate matching
