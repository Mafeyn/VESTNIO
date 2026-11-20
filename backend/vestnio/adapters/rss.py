"""RSS 2.0 / Atom / RDF adapter built on feedparser."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

import feedparser
from bs4 import BeautifulSoup

from ..domain import RawItem, SourceConfig
from ..fetcher import Fetcher
from .base import AdapterResult, CacheState, ParseError

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


class RssAdapter:
    name = "rss"

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult:
        result = await fetcher.get(str(source.url), etag=cache.etag, last_modified=cache.last_modified)
        new_cache = CacheState(result.headers.get("etag"), result.headers.get("last-modified"))
        if result.not_modified:
            return AdapterResult(not_modified=True, cache=cache)
        items = parse_feed(result.content, base_url=result.url)
        return AdapterResult(items=items, cache=new_cache)


def parse_feed(content: bytes | str, base_url: str | None = None) -> list[RawItem]:
    parsed = feedparser.parse(content, response_headers={"content-location": base_url} if base_url else None)
    if not parsed.entries and (parsed.get("bozo") or not parsed.get("version")):
        # an HTML error page or garbage, not an (empty) RSS/Atom feed
        reason = parsed.get("bozo_exception") or "unrecognized format"
        raise ParseError(f"not a valid feed: {reason!r}")
    feed_lang = (parsed.feed.get("language") or "").strip() or None
    return [_entry_to_item(e, feed_lang) for e in parsed.entries]


def _entry_to_item(entry: Any, feed_lang: str | None = None) -> RawItem:
    link = entry.get("link") or _first_alternate_link(entry)
    summary_html = entry.get("summary") or entry.get("description") or ""
    content_html = ""
    if entry.get("content"):
        content_html = entry.content[0].get("value", "")

    return RawItem(
        external_id=entry.get("id") or entry.get("guid") or link,
        title=entry.get("title"),
        url=link,
        summary=summary_html or None,
        image_url=_find_image(entry, summary_html, content_html),
        published=_entry_datetime(entry),
        language=(entry.get("language") or feed_lang),
    )


def _first_alternate_link(entry: Any) -> str | None:
    for link in entry.get("links", []):
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link["href"]
    return None


def _entry_datetime(entry: Any) -> datetime | str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            # feedparser normalizes *_parsed to UTC struct_time
            return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
    # fall back to the raw string; the normalizer will try harder
    return entry.get("published") or entry.get("updated")


def _find_image(entry: Any, summary_html: str, content_html: str) -> str | None:
    candidates: list[tuple[int, str]] = []  # (width or 0, url)

    for media in entry.get("media_content", []) or []:
        url = media.get("url")
        medium = media.get("medium", "")
        mtype = media.get("type", "")
        if url and (medium == "image" or mtype.startswith("image/") or _looks_like_image(url)):
            candidates.append((_int(media.get("width")), url))
    for thumb in entry.get("media_thumbnail", []) or []:
        if thumb.get("url"):
            candidates.append((_int(thumb.get("width")), thumb["url"]))
    if candidates:
        return max(candidates, key=lambda c: c[0])[1]

    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href and (enc.get("type", "").startswith("image/") or _looks_like_image(href)):
            return href

    if entry.get("image") and isinstance(entry.image, dict) and entry.image.get("href"):
        return entry.image["href"]

    for html in (content_html, summary_html):
        if html and "<img" in html:
            img = BeautifulSoup(html, "html.parser").find("img", src=True)
            if img and str(img["src"]).startswith("http"):
                return str(img["src"])
    return None


def _looks_like_image(url: str) -> bool:
    return url.lower().split("?")[0].endswith(IMAGE_EXTENSIONS)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
