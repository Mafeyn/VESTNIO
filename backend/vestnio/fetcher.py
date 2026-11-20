"""Feed Fetcher: polite HTTP client with timeouts, retries + exponential backoff,
robots.txt enforcement and conditional GET (ETag / Last-Modified)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Settings

log = logging.getLogger("vestnio.fetcher")

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
ROBOTS_TTL_SECONDS = 6 * 3600


class FetchError(Exception):
    """Raised when a resource could not be retrieved after all retries."""


class RobotsDisallowed(FetchError):
    """Raised when robots.txt forbids fetching a URL."""


@dataclass(slots=True)
class FetchResult:
    url: str  # final URL after redirects
    status_code: int
    content: bytes
    headers: httpx.Headers

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304

    @property
    def text(self) -> str:
        return self.content.decode(self._encoding(), errors="replace")

    def json(self):
        import json

        return json.loads(self.content)

    def _encoding(self) -> str:
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            return ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        return "utf-8"


class Fetcher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
                "application/json;q=0.9, text/html;q=0.8, */*;q=0.5",
            },
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}
        self._robots_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ robots
    async def allowed_by_robots(self, url: str) -> bool:
        if not self.settings.respect_robots_txt:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_lock:
            cached = self._robots.get(origin)
            if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_SECONDS:
                parser = await self._load_robots(origin)
                self._robots[origin] = (time.monotonic(), parser)
            parser = self._robots[origin][1]
        if parser is None:  # no robots.txt (404) => everything allowed
            return True
        return parser.can_fetch(self.settings.user_agent, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            resp = await self._client.get(robots_url)
        except httpx.HTTPError as exc:
            # Network trouble reading robots.txt: be conservative but don't block forever;
            # treat as "allowed" like most crawlers do for unreachable robots files.
            log.warning("robots.txt unreachable for %s: %s", origin, exc)
            return None
        if resp.status_code in (401, 403):
            parser.disallow_all = True
            return parser
        if resp.status_code >= 400:
            return None
        parser.parse(resp.text.splitlines())
        return parser

    # ------------------------------------------------------------------- fetch
    async def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        params: dict | None = None,
        check_robots: bool = True,
        retries: int | None = None,
        timeout: float | None = None,
        accept: str | None = None,
    ) -> FetchResult:
        if check_robots and not await self.allowed_by_robots(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if accept:
            headers["Accept"] = accept
        extra = {"timeout": timeout} if timeout is not None else {}

        attempts = max(1, (self.settings.max_retries if retries is None else retries) + 1)
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._client.get(url, headers=headers, params=params, **extra)
                if resp.status_code in RETRYABLE_STATUS:
                    raise _RetryableStatus(resp)
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} for {url}")
                return FetchResult(str(resp.url), resp.status_code, resp.content, resp.headers)
            except (httpx.TimeoutException, httpx.TransportError, _RetryableStatus) as exc:
                last_exc = exc
                if attempt == attempts:
                    break
                delay = self._backoff(attempt, exc)
                log.info("retry %d/%d for %s in %.1fs (%s)", attempt, attempts - 1, url, delay, _describe(exc))
                await asyncio.sleep(delay)
        raise FetchError(f"giving up on {url}: {_describe(last_exc)}") from last_exc

    def _backoff(self, attempt: int, exc: Exception) -> float:
        if isinstance(exc, _RetryableStatus):
            retry_after = exc.response.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                return min(float(retry_after), 60.0)
        base = self.settings.backoff_base_seconds * (2 ** (attempt - 1))
        return base + random.uniform(0, base / 2)


class _RetryableStatus(Exception):
    def __init__(self, response: httpx.Response):
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


def _describe(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
