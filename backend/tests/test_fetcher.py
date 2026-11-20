import httpx
import pytest
import respx

from vestnio.fetcher import Fetcher, FetchError, RobotsDisallowed

URL = "https://feeds.example.com/rss"


@pytest.fixture
def robots_ok():
    respx.get("https://feeds.example.com/robots.txt").respond(404)


@respx.mock
async def test_retries_then_succeeds(settings, robots_ok):
    route = respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.ConnectError("boom"), httpx.Response(200, text="<rss/>")])
    async with Fetcher(settings) as f:
        res = await f.get(URL)
    assert res.status_code == 200 and route.call_count == 3


@respx.mock
async def test_gives_up_after_max_retries(settings, robots_ok):
    route = respx.get(URL).respond(502)
    async with Fetcher(settings) as f:
        with pytest.raises(FetchError):
            await f.get(URL)
    assert route.call_count == settings.max_retries + 1


@respx.mock
async def test_timeout_is_retried_then_fails(settings, robots_ok):
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    async with Fetcher(settings) as f:
        with pytest.raises(FetchError, match="ReadTimeout"):
            await f.get(URL)


@respx.mock
async def test_client_errors_are_not_retried(settings, robots_ok):
    route = respx.get(URL).respond(404)
    async with Fetcher(settings) as f:
        with pytest.raises(FetchError, match="HTTP 404"):
            await f.get(URL)
    assert route.call_count == 1


@respx.mock
async def test_conditional_get_headers_and_304(settings, robots_ok):
    route = respx.get(URL).respond(304)
    async with Fetcher(settings) as f:
        res = await f.get(URL, etag='"abc"', last_modified="Thu, 19 Nov 2026 10:00:00 GMT")
    sent = route.calls.last.request.headers
    assert sent["if-none-match"] == '"abc"'
    assert sent["if-modified-since"] == "Thu, 19 Nov 2026 10:00:00 GMT"
    assert res.not_modified


@respx.mock
async def test_robots_txt_is_respected(settings):
    respx.get("https://feeds.example.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    page = respx.get(URL).respond(200, text="<rss/>")
    async with Fetcher(settings) as f:
        with pytest.raises(RobotsDisallowed):
            await f.get(URL)
    assert page.call_count == 0


@respx.mock
async def test_robots_403_means_disallow(settings):
    respx.get("https://feeds.example.com/robots.txt").respond(403)
    async with Fetcher(settings) as f:
        assert not await f.allowed_by_robots(URL)
