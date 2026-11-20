"""Site-specific HTML parsers.

Only for sites whose robots.txt permits automated access to the listing page.
Each source supplies CSS selectors in `options`, so a new site needs config, not code:

    options:
      item: "ul.topic-stories li"     # one element per article
      link: "a"                         # inside item; href = article URL, text = title
      title: "h3"                       # optional; defaults to the link text
      summary: "p.teaser"               # optional; a leading copy of the title is removed
      credit: "cite"                    # optional; original publisher, prefixed to the summary
      image: "img"                      # optional; uses src / data-src
      time: "time"                      # optional; uses datetime attr or text
      max_items: 40

Only headline, teaser and link are taken from the listing page; article bodies are
never fetched or stored.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..domain import RawItem, SourceConfig
from ..fetcher import Fetcher
from .base import AdapterResult, CacheState, ParseError


class CssHtmlAdapter:
    name = "html_css"

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult:
        # Fetcher.get enforces robots.txt (raises RobotsDisallowed).
        res = await fetcher.get(str(source.url), etag=cache.etag, last_modified=cache.last_modified)
        if res.not_modified:
            return AdapterResult(not_modified=True, cache=cache)
        items = parse_listing(res.text, res.url, source.options)
        return AdapterResult(
            items=items, cache=CacheState(res.headers.get("etag"), res.headers.get("last-modified"))
        )


def parse_listing(html: str, base_url: str, options: dict) -> list[RawItem]:
    item_sel = options.get("item")
    if not item_sel:
        raise ParseError("html_css source needs options.item")
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(item_sel)
    if not nodes:
        raise ParseError(f"selector {item_sel!r} matched nothing; the page layout may have changed")

    items: list[RawItem] = []
    seen: set[str] = set()
    for node in nodes[: int(options.get("max_items", 50))]:
        link = node.select_one(options.get("link", "a[href]")) if options.get("link") else node.find("a", href=True)
        if not isinstance(link, Tag) or not link.get("href"):
            continue
        url = urljoin(base_url, str(link["href"]))
        if url in seen:
            continue
        seen.add(url)
        title_node = node.select_one(options["title"]) if options.get("title") else link
        title = title_node.get_text(" ", strip=True) if title_node else None
        summary = _text(node, options.get("summary"))
        if summary and title and summary.startswith(title):
            # teaser containers often repeat the headline before the excerpt
            summary = summary[len(title) :].lstrip(" -–—:|").strip() or None
        credit = _text(node, options.get("credit"))
        if credit:
            credit = credit.rstrip(": ")
            summary = f"{credit}: {summary}" if summary else f"Via {credit}"
        items.append(
            RawItem(
                external_id=url,
                title=title,
                url=url,
                summary=summary,
                image_url=_image(node, options.get("image"), base_url),
                published=_time(node, options.get("time")),
            )
        )
    return items


def _text(node: Tag, selector: str | None) -> str | None:
    if not selector:
        return None
    el = node.select_one(selector)
    return el.get_text(" ", strip=True) if el else None


def _image(node: Tag, selector: str | None, base_url: str) -> str | None:
    if not selector:
        return None
    el = node.select_one(selector)
    if not el:
        return None
    src = el.get("data-src") or el.get("src")
    return urljoin(base_url, str(src)) if src else None


def _time(node: Tag, selector: str | None) -> str | None:
    if not selector:
        return None
    el = node.select_one(selector)
    if not el:
        return None
    return str(el.get("datetime") or el.get_text(strip=True)) or None
