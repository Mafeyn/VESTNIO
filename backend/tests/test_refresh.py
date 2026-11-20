"""Serverless self-refresh: collect in the background when the feed is stale."""

from datetime import datetime, timedelta, timezone

import respx
from sqlalchemy import text, update

from vestnio import refresh
from vestnio.db.models import Source
from vestnio.ingestion import IngestionService

from .conftest import requires_db

REGISTRY = """
defaults: {poll_minutes: 15, language: en}
sources:
  - {id: good, name: Good, url: "https://good.example/rss", category: world, method: rss, options: {enrich_images: false}}
"""


def _mock(fixture_bytes):
    respx.get("https://good.example/robots.txt").respond(404)
    return respx.get("https://good.example/rss").respond(200, content=fixture_bytes("rss2.xml"))


async def _setup(settings, sessionmaker, polled_minutes_ago):
    settings.sources_file.write_text(REGISTRY)
    service = IngestionService(settings, sessionmaker)
    await service.sync_registry()
    await service.aclose()
    if polled_minutes_ago is not None:
        async with sessionmaker() as s:
            await s.execute(
                update(Source).values(last_polled_at=datetime.now(timezone.utc) - timedelta(minutes=polled_minutes_ago))
            )
            await s.commit()
    refresh._last_check = 0.0


@requires_db
@respx.mock
async def test_stale_feed_triggers_collection(settings, sessionmaker, fixture_bytes):
    route = _mock(fixture_bytes)
    await _setup(settings, sessionmaker, polled_minutes_ago=60)
    assert await refresh.refresh_if_stale(settings) is True
    assert route.call_count == 1


@requires_db
@respx.mock
async def test_fresh_feed_is_left_alone(settings, sessionmaker, fixture_bytes):
    route = _mock(fixture_bytes)
    await _setup(settings, sessionmaker, polled_minutes_ago=3)
    assert await refresh.refresh_if_stale(settings) is False
    assert route.call_count == 0


@requires_db
@respx.mock
async def test_cooldown_and_lock(settings, sessionmaker, fixture_bytes):
    route = _mock(fixture_bytes)
    await _setup(settings, sessionmaker, polled_minutes_ago=60)
    # another instance holds the lock → nothing runs
    async with sessionmaker() as other:
        await other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": refresh.LOCK_KEY})
        assert await refresh.refresh_if_stale(settings) is False
        await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": refresh.LOCK_KEY})
    # within the cooldown the check isn't even repeated
    assert await refresh.refresh_if_stale(settings) is False
    assert route.call_count == 0
