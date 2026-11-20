"""Public API response models. Every response is either
    {"data": ..., "meta": {...}}   or   {"error": {"code", "message", "details"}}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, field_serializer

T = TypeVar("T")


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _utc(self, v: Any):  # timestamps are always serialized as UTC: 2026-11-20T08:15:00Z
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return v


class SourceRef(_Model):
    id: str
    name: str
    homepage: str | None


class ArticleOut(_Model):
    id: int
    title: str
    summary: str | None
    image_url: str | None
    url: str
    published_at: datetime
    published_estimated: bool
    language: str | None
    category: str
    source: SourceRef


class ArticleDetailOut(ArticleOut):
    canonical_url: str
    fetched_at: datetime


class CategoryOut(_Model):
    id: str
    label: str
    article_count: int
    last_24h: int
    source_count: int
    latest_published_at: datetime | None


class SourceOut(_Model):
    id: str
    name: str
    homepage: str | None
    category: str
    method: str
    enabled: bool
    status: str
    poll_minutes: int
    last_success_at: datetime | None
    last_polled_at: datetime | None
    last_error: str | None
    article_count: int


class ListMeta(_Model):
    count: int
    limit: int | None = None
    next_cursor: str | None = None
    sort: str | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: ListMeta | dict[str, Any] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class HealthOut(_Model):
    status: Literal["ok", "degraded", "down"]
    database: Literal["ok", "unavailable"]
    articles: int
    last_successful_fetch: datetime | None
    sources: dict[str, int]
    version: str
