from datetime import datetime, timedelta, timezone

import pytest

from vestnio.domain import RawItem, SourceConfig
from vestnio.normalizer import InvalidItem, make_summary, normalize, normalize_many, parse_datetime

UTC = timezone.utc
SRC = SourceConfig(id="src-a", name="A", url="https://a.example/rss", category="gaming", method="rss", language="en")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Thu, 19 Nov 2026 14:30:00 +0100", datetime(2026, 11, 19, 13, 30, tzinfo=UTC)),
        ("Thu, 19 Nov 2026 14:30:00 GMT", datetime(2026, 11, 19, 14, 30, tzinfo=UTC)),
        ("2026-11-19T21:15:00-05:00", datetime(2026, 11, 20, 2, 15, tzinfo=UTC)),
        ("2026-11-19T21:15:00Z", datetime(2026, 11, 19, 21, 15, tzinfo=UTC)),
        ("2026-11-19T21:15:00", datetime(2026, 11, 19, 21, 15, tzinfo=UTC)),  # naive -> UTC
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_datetime_normalizes_to_utc(raw, expected):
    assert parse_datetime(raw) == expected


def test_normalize_cleans_fields():
    item = RawItem(
        title="  Big &amp; <b>bold</b>\n headline ",
        url="https://www.a.example/news/1/?utm_source=rss#top",
        summary="<p>First&nbsp;para.</p> The post Big appeared first on A.",
        image_url="//cdn.a.example/i.jpg",
        published="2026-11-19T10:00:00+02:00",
    )
    a = normalize(item, SRC)
    assert a.title == "Big & bold headline"
    assert a.summary == "First para."
    assert a.image_url == "https://cdn.a.example/i.jpg"
    assert a.canonical_url == "https://a.example/news/1"
    assert a.published_at == datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
    assert a.external_id == a.canonical_url  # no GUID -> canonical URL
    assert a.category.value == "gaming" and a.language == "en"


def test_missing_and_future_dates_use_fetch_time():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    undated = normalize(RawItem(title="t", url="https://a.example/x"), SRC, now)
    assert undated.published_at == now and undated.published_estimated
    future = normalize(RawItem(title="t", url="https://a.example/y", published=now + timedelta(days=2)), SRC, now)
    assert future.published_at == now


def test_feed_language_wins_over_source_default():
    a = normalize(RawItem(title="Hallo Welt", url="https://a.example/de", language="de-DE"), SRC)
    assert a.language == "de-de"


def test_invalid_items_are_skipped():
    with pytest.raises(InvalidItem):
        normalize(RawItem(title="", url="https://a.example/x"), SRC)
    with pytest.raises(InvalidItem):
        normalize(RawItem(title="ok", url="javascript:alert(1)"), SRC)
    out = normalize_many([RawItem(title="", url="https://a.example/1"), RawItem(title="Fine", url="https://a.example/2")], SRC)
    assert [a.title for a in out] == ["Fine"]


def test_undated_items_keep_page_order():
    out = normalize_many([RawItem(title=f"Item {i}", url=f"https://a.example/{i}") for i in range(3)], SRC)
    assert out[0].published_at > out[1].published_at > out[2].published_at


def test_summary_truncation_and_title_echo():
    assert make_summary("Same title", "same TITLE") is None
    long = "word " * 200
    s = make_summary(long, "t")
    assert len(s) <= 321 and s.endswith("…")
