import respx

from vestnio.domain import RawItem, SourceConfig
from vestnio.enrich import enrich_images, extract_preview_image
from vestnio.fetcher import Fetcher
from vestnio.normalizer import normalize

SRC = SourceConfig(id="src-s", name="S", url="https://news.example.com/rss", category="world", method="rss")


def test_extract_prefers_og_image_and_resolves_relative():
    html = """<html><head>
      <meta name="twitter:image" content="https://cdn.example.com/tw.jpg">
      <meta content="/img/cover.jpg?w=1200&amp;h=630" property="og:image" />
    </head><body><img src="/body.jpg"></body></html>"""
    assert extract_preview_image(html, "https://news.example.com/a/1") == "https://news.example.com/img/cover.jpg?w=1200&h=630"


def test_extract_ignores_logos_and_missing_tags():
    assert extract_preview_image('<meta property="og:image" content="https://x.example/static/logo.png">', "https://x.example") is None
    assert extract_preview_image("<html><head><title>t</title></head></html>", "https://x.example") is None


@respx.mock
async def test_enrich_fills_only_missing_and_respects_robots(settings):
    respx.get("https://news.example.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /private/")
    respx.get("https://news.example.com/a/1").respond(
        200, html='<head><meta property="og:image" content="https://cdn.example.com/1.jpg"></head>'
    )
    blocked = respx.get("https://news.example.com/private/2").respond(200, html="<head></head>")
    respx.get("https://news.example.com/a/3").respond(404)
    arts = [
        normalize(RawItem(title="One", url="https://news.example.com/a/1"), SRC),
        normalize(RawItem(title="Two", url="https://news.example.com/private/2"), SRC),
        normalize(RawItem(title="Three", url="https://news.example.com/a/3"), SRC),
        normalize(RawItem(title="Four", url="https://news.example.com/a/4", image_url="https://cdn.example.com/own.jpg"), SRC),
    ]
    async with Fetcher(settings) as f:
        found = await enrich_images(arts, f)
    assert found == 1
    assert arts[0].image_url == "https://cdn.example.com/1.jpg"
    assert arts[1].image_url is None and blocked.call_count == 0  # robots.txt disallows
    assert arts[2].image_url is None  # 404 is fine, no retry storm
    assert arts[3].image_url == "https://cdn.example.com/own.jpg"  # feed image kept
