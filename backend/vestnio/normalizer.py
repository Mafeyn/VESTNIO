"""News Normalizer: cleans RawItem fields into a consistent NormalizedArticle."""

from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from .dedup import canonicalize_url, title_fingerprint, url_hash
from .domain import NormalizedArticle, RawItem, SourceConfig

log = logging.getLogger("vestnio.normalizer")

SUMMARY_MAX_CHARS = 320
TITLE_MAX_CHARS = 400
FUTURE_TOLERANCE = timedelta(hours=1)
_WS = re.compile(r"\s+")
# WordPress / Feedburner boilerplate appended to excerpts
_TRAILERS = [
    re.compile(r"\s*The post .{1,300}? appeared first on .{1,200}?\.?\s*$", re.I | re.S),
    re.compile(r"\s*(Continue reading|Read more|Read the full story)\b.*$", re.I | re.S),
    re.compile(r"\s*\[(…|\.\.\.|&#8230;)\]\s*$"),
]


class InvalidItem(ValueError):
    pass


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    if "<" in value and ">" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    value = html.unescape(value).replace(" ", " ")
    return _WS.sub(" ", value).strip()


def make_summary(raw: str | None, title: str) -> str | None:
    text = clean_text(raw)
    for pattern in _TRAILERS:
        text = pattern.sub("", text).strip()
    if not text or text.casefold() == title.casefold():
        return None
    if len(text) > SUMMARY_MAX_CHARS:
        cut = text[:SUMMARY_MAX_CHARS]
        cut = cut[: cut.rfind(" ")] if " " in cut[200:] else cut
        text = cut.rstrip(" ,;:.-–—") + "…"
    return text


def parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = value.strip()
        if not s:
            return None
        dt = None
        try:
            dt = parsedate_to_datetime(s)  # RFC 822 / 2822
        except (TypeError, ValueError, IndexError):
            pass
        if dt is None:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO 8601
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # naive timestamps are assumed UTC
    return dt.astimezone(timezone.utc)


def normalize(item: RawItem, source: SourceConfig, fetched_at: datetime | None = None) -> NormalizedArticle:
    fetched_at = fetched_at or datetime.now(timezone.utc)

    title = clean_text(item.title)[:TITLE_MAX_CHARS]
    if not title:
        raise InvalidItem("missing title")

    url = (item.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise InvalidItem(f"missing or non-http url: {url!r}")
    canonical = canonicalize_url(url)

    published = parse_datetime(item.published)
    estimated = published is None
    if published is None or published > fetched_at + FUTURE_TOLERANCE:
        published = fetched_at

    image = (item.image_url or "").strip() or None
    if image and image.startswith("//"):
        image = "https:" + image
    if image and not image.lower().startswith(("http://", "https://")):
        image = None

    external_id = (item.external_id or "").strip() or canonical
    if len(external_id) > 500:
        external_id = "sha256:" + hashlib.sha256(external_id.encode()).hexdigest()

    return NormalizedArticle(
        source_id=source.id,
        category=source.category,
        external_id=external_id,
        title=title,
        summary=make_summary(item.summary, title),
        image_url=image[:1000] if image else None,
        url=url[:2000],
        canonical_url=canonical[:2000],
        url_hash=url_hash(canonical),
        published_at=published,
        published_estimated=estimated,
        language=_language(item.language or source.language),
        title_fp=title_fingerprint(title),
    )


def _language(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().replace("_", "-").lower()
    return code[:16] if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", code) else None


def normalize_many(items: list[RawItem], source: SourceConfig) -> list[NormalizedArticle]:
    fetched_at = datetime.now(timezone.utc)
    out: list[NormalizedArticle] = []
    for i, item in enumerate(items):
        try:
            # Undated items get "first seen" time; subtracting the position keeps the
            # publisher's on-page order instead of a block of identical timestamps.
            out.append(normalize(item, source, fetched_at - timedelta(seconds=i)))
        except InvalidItem as exc:
            log.debug("skipping item from %s: %s", source.id, exc)
    return out
