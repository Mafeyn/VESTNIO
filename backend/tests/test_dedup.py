from datetime import datetime, timedelta, timezone

import pytest

from vestnio.db import repository as repo
from vestnio.dedup import canonicalize_url, dedupe_batch, title_fingerprint
from vestnio.domain import RawItem, SourceConfig
from vestnio.normalizer import normalize

from .conftest import requires_db

UTC = timezone.utc


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://www.example.com/a/b/?utm_source=x&id=2", "http://example.com/a/b?id=2"),
        ("https://example.com/a?b=2&a=1", "https://EXAMPLE.com/a?a=1&b=2"),
        ("https://example.com/a#comments", "https://example.com/a"),
        ("https://example.com:443/a?fbclid=123&gclid=4", "https://example.com/a"),
    ],
)
def test_canonical_url_equivalence(a, b):
    assert canonicalize_url(a) == canonicalize_url(b)


def test_canonical_url_keeps_meaningful_params():
    assert canonicalize_url("https://example.com/watch?v=abc") != canonicalize_url("https://example.com/watch?v=xyz")


def test_title_fingerprint():
    assert title_fingerprint("Valve warns of a possible Steam Machine price hike") == title_fingerprint(
        "Valve Warns of a Possible Steam Machine Price-Hike!"
    )
    assert title_fingerprint("Live updates") is None  # too short to be distinctive


def _src(sid: str) -> SourceConfig:
    return SourceConfig(id=sid, name=sid, url=f"https://{sid}.example/rss", category="technology", method="rss")


def _art(sid: str, guid: str, url: str, title: str = "A perfectly ordinary five word headline", when=None):
    return normalize(
        RawItem(title=title, url=url, external_id=guid, published=when or datetime.now(UTC) - timedelta(hours=1)),
        _src(sid),
    )


def test_dedupe_batch_rules():
    batch = [
        _art("s1", "g1", "https://x.example/1", "Unique headline number one goes here"),
        _art("s1", "g1", "https://x.example/1-moved", "Unique headline number one goes here!"),  # same GUID
        _art("s1", "g2", "https://www.x.example/1/?utm_medium=rss", "Something else entirely different here"),  # same URL
        _art("s1", "g3", "https://x.example/3", "UNIQUE headline number one goes here"),  # same fingerprint
        _art("s1", "g4", "https://x.example/4", "Fresh distinct headline for item four"),
    ]
    assert [a.external_id for a in dedupe_batch(batch)] == ["g1", "g4"]


# ------------------------------------------------------------- database rules
async def _sync(sm, *ids):
    async with sm() as s:
        await repo.sync_sources(s, [_src(i) for i in ids], 15)


@requires_db
async def test_db_dedup_by_guid_url_and_fingerprint(sessionmaker):
    await _sync(sessionmaker, "s1", "s2")
    async with sessionmaker() as s:
        first = [
            _art("s1", "g1", "https://x.example/1", "Original story about the new console launch"),
            _art("s1", "g2", "https://x.example/2", "Another story about a totally different topic"),
        ]
        assert await repo.insert_articles(s, first) == 2
        # identical re-poll -> nothing new
        assert await repo.insert_articles(s, first) == 0
        again = [
            # same GUID from same source, edited URL -> duplicate (rule 1)
            _art("s1", "g1", "https://x.example/1-edited", "Original story about the new console launch (updated)"),
            # other source, same canonical URL -> duplicate (rule 2)
            _art("s2", "zz", "https://www.x.example/2/?utm_source=s2", "Different headline wording entirely here"),
            # other source, new GUID + URL, same normalized title -> duplicate (rule 3)
            _art("s2", "yy", "https://mirror.example/a", "Original Story About The New Console Launch"),
            # genuinely new
            _art("s2", "new", "https://y.example/new", "Something completely new happened today"),
        ]
        assert await repo.insert_articles(s, again) == 1


@requires_db
async def test_fingerprint_rule_expires(sessionmaker):
    await _sync(sessionmaker, "s1", "s2")
    old = datetime.now(UTC) - timedelta(days=5)
    async with sessionmaker() as s:
        assert await repo.insert_articles(s, [_art("s1", "g1", "https://x.example/old", "Annual awards show returns next week", old)]) == 1
        # a year-on-year headline outside the 72h window is a different story
        assert await repo.insert_articles(s, [_art("s2", "g9", "https://x.example/new", "Annual awards show returns next week")]) == 1
