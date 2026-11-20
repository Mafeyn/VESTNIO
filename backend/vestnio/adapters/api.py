"""Adapters for official news APIs.

Official APIs are governed by their terms of use rather than robots.txt, so these
adapters call them directly and stay within their documented rate limits.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..config import get_settings
from ..domain import RawItem, SourceConfig
from ..fetcher import FetchError, Fetcher
from .base import AdapterResult, CacheState, MissingCredentials, ParseError


class HackerNewsAdapter:
    """Hacker News official Firebase API (https://github.com/HackerNews/API).

    `url` points at a story list endpoint such as .../v0/topstories.json.
    options.limit: number of stories to pull per poll (default 30).
    """

    name = "hackernews"
    ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
    DISCUSSION_URL = "https://news.ycombinator.com/item?id={id}"

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult:
        limit = int(source.options.get("limit", 30))
        listing = await fetcher.get(str(source.url), check_robots=False)
        try:
            ids = list(listing.json())[:limit]
        except ValueError as exc:
            raise ParseError(f"invalid story list: {exc}") from exc

        sem = asyncio.Semaphore(8)

        async def one(story_id: int) -> RawItem | None:
            async with sem:
                try:
                    res = await fetcher.get(self.ITEM_URL.format(id=story_id), check_robots=False)
                    data = res.json()
                except (FetchError, ValueError):
                    return None  # a single broken item must not sink the whole poll
            if not data or data.get("type") != "story" or data.get("dead") or data.get("deleted"):
                return None
            discussion = self.DISCUSSION_URL.format(id=story_id)
            points, comments = data.get("score", 0), data.get("descendants", 0)
            return RawItem(
                external_id=f"hn:{story_id}",
                title=data.get("title"),
                url=data.get("url") or discussion,
                summary=f"{points} points · {comments} comments on Hacker News",
                published=datetime.fromtimestamp(data["time"], tz=timezone.utc) if data.get("time") else None,
                extra={"discussion_url": discussion},
            )

        items = [i for i in await asyncio.gather(*(one(i) for i in ids)) if i]
        return AdapterResult(items=items)


class GuardianAdapter:
    """The Guardian Open Platform Content API (https://open-platform.theguardian.com/).

    Requires VESTNIO_GUARDIAN_API_KEY. options.section: Guardian section id (e.g. "world").
    """

    name = "guardian"

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult:
        secret = get_settings().guardian_api_key
        key = secret.get_secret_value() if secret else ""
        if not key:
            raise MissingCredentials("VESTNIO_GUARDIAN_API_KEY is not set")
        params = {
            "api-key": key,
            "order-by": "newest",
            "page-size": str(source.options.get("page_size", 30)),
            "show-fields": "trailText,thumbnail",
        }
        if source.options.get("section"):
            params["section"] = source.options["section"]
        res = await fetcher.get(str(source.url), params=params, check_robots=False)
        try:
            payload = res.json()["response"]
        except (ValueError, KeyError) as exc:
            raise ParseError(f"unexpected Guardian response: {exc}") from exc
        if payload.get("status") != "ok":
            raise ParseError(f"Guardian API status {payload.get('status')}: {payload.get('message')}")

        items = []
        for r in payload.get("results", []):
            fields = r.get("fields") or {}
            items.append(
                RawItem(
                    external_id=r.get("id"),
                    title=r.get("webTitle"),
                    url=r.get("webUrl"),
                    summary=fields.get("trailText"),
                    image_url=fields.get("thumbnail"),
                    published=r.get("webPublicationDate"),
                    language="en",
                )
            )
        return AdapterResult(items=items)
