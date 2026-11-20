"""Cover-image enrichment for articles whose feed carries no picture.

Reads only the publisher's own preview metadata (<meta property="og:image"> /
twitter:image) from the article page — the same data Telegram and social networks
use to build link previews. The article body is never parsed or stored.

Politeness: robots.txt is checked for every page, one attempt, short timeout,
at most `limit` pages per poll and a few in parallel. Only *new* articles are
enriched, so a page is requested at most once.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from urllib.parse import urljoin

from .domain import NormalizedArticle
from .fetcher import FetchError, Fetcher

log = logging.getLogger("vestnio.enrich")

HEAD_BYTES = 256 * 1024  # og tags live in <head>; don't scan megabytes of body
_META = re.compile(r"<meta\b[^>]*>", re.I | re.S)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.S)
PREFERRED = ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
_BAD = re.compile(r"(logo|favicon|placeholder|default|blank|sprite)[^/]*\.(png|svg|gif|jpe?g|webp)$", re.I)


def extract_preview_image(html: str, base_url: str) -> str | None:
    found: dict[str, str] = {}
    for tag in _META.findall(html[:HEAD_BYTES]):
        attrs = {m.group(1).lower(): (m.group(2) or m.group(3) or m.group(4) or "") for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in PREFERRED and attrs.get("content") and key not in found:
            found[key] = attrs["content"].strip()
    for key in PREFERRED:
        url = found.get(key)
        if not url:
            continue
        url = urljoin(base_url, url.replace("&amp;", "&"))
        if url.startswith(("http://", "https://")) and not _BAD.search(url.split("?")[0]):
            return url[:1000]
    return None


async def enrich_images(
    articles: Sequence[NormalizedArticle],
    fetcher: Fetcher,
    *,
    limit: int = 25,
    concurrency: int = 4,
    timeout: float = 8.0,
) -> int:
    """Fill image_url in place for articles that lack one. Returns how many were found."""
    todo = [a for a in articles if not a.image_url][:limit]
    if not todo:
        return 0
    sem = asyncio.Semaphore(concurrency)

    async def one(a: NormalizedArticle) -> bool:
        async with sem:
            try:
                res = await fetcher.get(a.url, retries=0, timeout=timeout, accept="text/html,application/xhtml+xml")
            except FetchError as exc:  # includes RobotsDisallowed
                log.debug("no preview image for %s: %s", a.url, exc)
                return False
            except Exception as exc:  # never let enrichment break ingestion
                log.debug("preview fetch failed for %s: %s", a.url, exc)
                return False
        if "html" not in res.headers.get("content-type", "html"):
            return False
        img = extract_preview_image(res.content[:HEAD_BYTES].decode("utf-8", errors="replace"), res.url)
        if img:
            a.image_url = img
            return True
        return False

    results = await asyncio.gather(*(one(a) for a in todo))
    return sum(results)
