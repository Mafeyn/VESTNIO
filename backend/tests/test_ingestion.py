"""Pipeline reliability: source isolation, status tracking, conditional requests."""

from datetime import datetime, timedelta, timezone

import httpx
import respx
from sqlalchemy import func, select

from vestnio.db import repository as repo
from vestnio.db.models import Article, IngestionRun
from vestnio.ingestion import IngestionService
from vestnio.source_manager import is_due, load_registry, next_poll_at
from vestnio.worker import IngestionWorker

from .conftest import requires_db

REGISTRY = """
defaults: {poll_minutes: 15, language: en}
sources:
  - {id: good, name: Good, url: "https://good.example/rss", category: world, method: rss}
  - {id: down, name: Down, url: "https://down.example/rss", category: world, method: rss}
  - {id: garbage, name: Garbage, url: "https://garbage.example/rss", category: gaming, method: rss}
  - {id: paused, name: Paused, url: "https://paused.example/rss", category: gaming, method: rss, enabled: false}
"""


def _mock_sources(fixture_bytes):
    for host in ("good", "down", "garbage", "paused"):
        respx.get(f"https://{host}.example/robots.txt").respond(404)
    respx.get("https://good.example/rss").respond(200, content=fixture_bytes("rss2.xml"), headers={"ETag": '"v1"'})
    respx.get("https://down.example/rss").respond(500)
    respx.get("https://garbage.example/rss").respond(200, text="<html>not a feed</html>")


@requires_db
@respx.mock
async def test_failing_sources_do_not_block_others(settings, sessionmaker, fixture_bytes):
    settings.sources_file.write_text(REGISTRY)
    _mock_sources(fixture_bytes)
    service = IngestionService(settings, sessionmaker)
    await service.sync_registry()
    results = {r.source_id: r for r in await service.poll_all()}
    await service.aclose()

    assert set(results) == {"good", "down", "garbage"}  # disabled source not polled
    assert results["good"].ok and results["good"].inserted == 3  # 4 items, 1 without title
    assert not results["down"].ok and "HTTP 500" in results["down"].error
    assert not results["garbage"].ok and "ParseError" in results["garbage"].error

    async with sessionmaker() as s:
        rows = {r.id: r for r in await repo.list_sources(s)}
        assert rows["good"].status == "healthy" and rows["good"].last_success_at is not None
        assert rows["good"].etag == '"v1"'
        assert rows["down"].status == "degraded" and rows["down"].consecutive_failures == 1
        assert rows["paused"].status == "disabled"
        assert await s.scalar(select(func.count()).select_from(Article)) == 3
        assert await s.scalar(select(func.count()).select_from(IngestionRun).where(IngestionRun.ok.is_(False))) == 2


@requires_db
@respx.mock
async def test_conditional_request_and_idempotent_repoll(settings, sessionmaker, fixture_bytes):
    settings.sources_file.write_text(REGISTRY)
    _mock_sources(fixture_bytes)
    service = IngestionService(settings, sessionmaker)
    await service.sync_registry()
    await service.poll_source_id("good")

    route = respx.get("https://good.example/rss").respond(304)
    second = await service.poll_source_id("good")
    await service.aclose()
    assert second.ok and second.not_modified and second.inserted == 0
    assert route.calls.last.request.headers["if-none-match"] == '"v1"'


@requires_db
@respx.mock
async def test_repeated_failures_mark_failing_and_back_off(settings, sessionmaker, fixture_bytes):
    settings.sources_file.write_text(REGISTRY)
    _mock_sources(fixture_bytes)
    service = IngestionService(settings, sessionmaker)
    await service.sync_registry()
    for _ in range(4):
        await service.poll_source_id("down")
    await service.aclose()
    async with sessionmaker() as s:
        row = await repo.get_source(s, "down")
    assert row.status == "failing" and row.consecutive_failures == 4
    # 4 failures -> poll interval x4 (15 -> 60 min)
    assert next_poll_at(row) == row.last_polled_at + timedelta(minutes=60)
    assert not is_due(row, row.last_polled_at + timedelta(minutes=30))


@requires_db
async def test_worker_schedules_one_job_per_enabled_source(settings, sessionmaker):
    settings.sources_file.write_text(REGISTRY)
    worker = IngestionWorker(IngestionService(settings, sessionmaker))
    await worker.reload_registry(first_run=True)
    jobs = {j.id: j for j in worker.scheduler.get_jobs()}
    assert set(jobs) == {"source:good", "source:down", "source:garbage"}

    # removing a source from the registry unschedules it
    settings.sources_file.write_text(REGISTRY.replace('  - {id: down, name: Down, url: "https://down.example/rss", category: world, method: rss}\n', ""))
    await worker.reload_registry()
    assert {j.id for j in worker.scheduler.get_jobs()} == {"source:good", "source:garbage"}
    await worker.service.aclose()


def test_registry_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources:\n  - {id: a, name: A, url: 'https://a.example', category: sports, method: rss}\n  - {id: a, name: A2, url: 'https://b.example', category: world, method: rss}\n")
    import pytest

    from vestnio.source_manager import RegistryError

    with pytest.raises(RegistryError):
        load_registry(bad)


def test_shipped_registry_is_valid():
    from vestnio.config import BACKEND_DIR

    configs = load_registry(BACKEND_DIR / "sources.yaml")
    enabled = [c for c in configs if c.enabled]
    assert len(enabled) >= 5
    assert {c.category.value for c in enabled} == {"gaming", "world", "technology"}
    assert {c.method.value for c in configs} == {"rss", "api", "html", "telegram"}  # every ingestion type is configured
