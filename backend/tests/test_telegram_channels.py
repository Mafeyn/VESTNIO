from datetime import datetime, timezone

import pytest
import respx

from vestnio import adapters
from vestnio.adapters.base import ParseError
from vestnio.adapters.telegram import channel_from_url, parse_channel_page, split_title
from vestnio.domain import SourceConfig
from vestnio.fetcher import Fetcher
from vestnio.normalizer import normalize_many


def _items(fixture_bytes):
    return parse_channel_page(fixture_bytes("tg_channel.html").decode(), "pda_4", source_name="4PDA Community")


def test_posts_become_articles_newest_first(fixture_bytes):
    items = _items(fixture_bytes)
    # service message, ad (erid) and caption-less photo are skipped
    assert [i.external_id for i in items] == ["tg:pda_4/103", "tg:pda_4/100"]
    post = items[1]
    assert post.title == "IPO Anthropic стартовало — акции можно купить на бирже."  # leading emoji stripped
    assert post.url == "https://t.me/pda_4/100"
    assert post.summary == "Официальная стартовая цена — $83."  # "❤️ PDA" signature dropped
    assert post.image_url == "https://cdn4.telesco.pe/file/abc.jpg"
    assert post.published == "2026-11-20T08:34:00+00:00"


def test_long_first_line_is_cut_at_sentence_and_promo_removed(fixture_bytes):
    long_post = _items(fixture_bytes)[0]
    assert long_post.title.endswith("событиях.") and len(long_post.title) <= 140
    assert long_post.summary.startswith("Второе предложение")
    assert "Подписаться" not in long_post.summary
    assert long_post.image_url == "https://cdn4.telesco.pe/file/video.jpg"  # protocol-relative fixed


def test_normalized_timestamps_are_utc(fixture_bytes):
    src = SourceConfig(id="tg-4pda", name="4PDA Community", url="https://t.me/s/pda_4", category="technology", method="telegram", language="ru")
    arts = normalize_many(_items(fixture_bytes), src)
    assert arts[1].published_at == datetime(2026, 11, 20, 8, 34, tzinfo=timezone.utc)
    assert arts[1].language == "ru" and not arts[1].published_estimated


@pytest.mark.parametrize(
    "text, title, rest",
    [
        ("Короткий заголовок\nТекст", "Короткий заголовок", "Текст"),
        ("🔥🔥 Срочно: новость", "Срочно: новость", ""),
        ("", "", ""),
    ],
)
def test_split_title(text, title, rest):
    assert split_title(text) == (title, rest)


def test_channel_from_url():
    assert channel_from_url("https://t.me/s/pda_4") == "pda_4"
    assert channel_from_url("https://t.me/pda_4") == "pda_4"


def test_not_a_channel_page():
    with pytest.raises(ParseError):
        parse_channel_page("<html><body>nothing</body></html>", "x")


@respx.mock
async def test_private_channel_without_preview_is_an_error(settings):
    respx.get("https://t.me/robots.txt").respond(404)
    respx.get("https://t.me/s/secret").respond(302, headers={"Location": "https://t.me/secret"})
    respx.get("https://t.me/secret").respond(200, text="<html></html>")
    src = SourceConfig(id="tg-secret", name="Secret", url="https://t.me/s/secret", category="world", method="telegram")
    async with Fetcher(settings) as f:
        with pytest.raises(ParseError, match="no public web preview"):
            await adapters.get_adapter(src).fetch(src, f, adapters.CacheState())
