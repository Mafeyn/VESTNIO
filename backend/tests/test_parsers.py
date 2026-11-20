from datetime import datetime, timezone

import httpx
import pytest
import respx

from vestnio import adapters
from vestnio.adapters.html import parse_listing
from vestnio.adapters.rss import parse_feed
from vestnio.domain import SourceConfig
from vestnio.fetcher import Fetcher

UTC = timezone.utc


def _src(**kw) -> SourceConfig:
    base = dict(id="test-src", name="Test", url="https://feed.example.com/rss", category="world", method="rss")
    return SourceConfig.model_validate({**base, **kw})


# ------------------------------------------------------------------ RSS 2.0
def test_rss2_extracts_fields(fixture_bytes):
    items = parse_feed(fixture_bytes("rss2.xml"))
    assert len(items) == 4
    first = items[0]
    assert first.external_id == "ex-1001"
    assert first.title == "Leaders meet & agree on   climate deal"
    assert first.url.startswith("https://news.example.com/world/climate-deal")
    assert first.published == datetime(2026, 11, 19, 13, 30, tzinfo=UTC)  # +0100 -> UTC
    assert first.image_url == "https://img.example.com/large.jpg"  # widest media wins
    assert first.language == "en-gb"
    assert "40 countries" in first.summary


def test_rss2_enclosure_image_and_missing_image(fixture_bytes):
    items = parse_feed(fixture_bytes("rss2.xml"))
    assert items[1].image_url is None
    assert items[2].image_url == "https://img.example.com/enc.png"


# --------------------------------------------------------------------- Atom
def test_atom_extracts_fields(fixture_bytes):
    items = parse_feed(fixture_bytes("atom.xml"))
    assert len(items) == 2
    e = items[0]
    assert e.external_id == "tag:tech.example.com,2026:entry-77"
    assert e.url == "https://tech.example.com/2026/11/chip/"
    assert e.published == datetime(2026, 11, 20, 2, 15, tzinfo=UTC)  # -05:00 -> UTC, "published" preferred
    assert e.image_url == "https://tech.example.com/img/chip.webp"  # from <content> html
    assert items[1].published == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)  # falls back to <updated>


def test_rdf_feed(fixture_bytes):
    items = parse_feed(fixture_bytes("rdf.xml"))
    assert items[0].title == "Nachricht eins"
    assert items[0].language == "de"  # original language preserved
    assert items[0].published == datetime(2026, 11, 19, 20, 53, tzinfo=UTC)


def test_invalid_feed_raises():
    with pytest.raises(adapters.ParseError):
        parse_feed(b"<html><body>Service unavailable</body></html>")


# --------------------------------------------------------------------- HTML
def test_html_listing(fixture_bytes):
    opts = {
        "item": "div.clus",
        "link": "div.ii strong a.ourh",
        "title": "div.ii strong a.ourh",
        "summary": "div.ii",
        "credit": "cite",
    }
    items = parse_listing(fixture_bytes("listing.html").decode(), "https://agg.example.com/", opts)
    assert [i.url for i in items] == [
        "https://publisher.example.com/story-1",
        "https://agg.example.com/relative/story-2",  # resolved against the page URL
    ]  # cluster without link skipped, repeated URL skipped
    assert items[0].title == "Company ships first product to customers"
    assert items[0].summary.startswith("Publisher: The company said shipments began")  # title stripped
    assert items[0].published is None


def test_html_listing_layout_change_is_an_error():
    with pytest.raises(adapters.ParseError):
        parse_listing("<html><body><p>redesigned</p></body></html>", "https://x.example/", {"item": "div.clus"})


# -------------------------------------------------------------- API adapters
@respx.mock
async def test_hackernews_adapter(settings):
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").respond(json=[1, 2, 3])
    respx.get("https://hacker-news.firebaseio.com/v0/item/1.json").respond(
        json={"id": 1, "type": "story", "title": "Show HN: a thing", "url": "https://thing.example/", "time": 1763596800, "score": 10, "descendants": 2}
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/2.json").respond(
        json={"id": 2, "type": "story", "title": "Ask HN: question?", "time": 1763596900}
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/3.json").respond(500)  # one broken item
    src = _src(method="api", adapter="hackernews", url="https://hacker-news.firebaseio.com/v0/topstories.json", category="technology")
    async with Fetcher(settings) as f:
        res = await adapters.get_adapter(src).fetch(src, f, adapters.CacheState())
    assert [i.external_id for i in res.items] == ["hn:1", "hn:2"]
    assert res.items[0].url == "https://thing.example/"
    assert res.items[1].url == "https://news.ycombinator.com/item?id=2"  # Ask HN -> discussion page
    assert res.items[0].published == datetime.fromtimestamp(1763596800, UTC)


async def test_guardian_without_key_is_skipped(settings, monkeypatch):
    monkeypatch.delenv("VESTNIO_GUARDIAN_API_KEY", raising=False)
    src = _src(method="api", adapter="guardian", url="https://content.guardianapis.com/search")
    async with Fetcher(settings) as f:
        with pytest.raises(adapters.MissingCredentials):
            await adapters.get_adapter(src).fetch(src, f, adapters.CacheState())


def test_adapter_method_mismatch_rejected():
    with pytest.raises(ValueError):
        adapters.get_adapter(_src(method="rss", adapter="hackernews"))
    with pytest.raises(KeyError):
        adapters.get_adapter(_src(method="api"))  # api needs a named adapter
