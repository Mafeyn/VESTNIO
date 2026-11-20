"""Ingestion service: Source Manager -> Feed Fetcher -> Parser Adapter ->
News Normalizer -> Duplicate Filter -> Database Layer.

Every source is processed in isolation: an exception in one source is caught,
logged against that source, and never interrupts the others. Scheduling lives
in vestnio.worker (APScheduler).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import adapters
from .config import Settings
from .db import repository as repo
from .db.models import Source
from .dedup import dedupe_batch
from .domain import IngestionMethod, SourceConfig, SourceStatus
from .enrich import enrich_images
from .fetcher import Fetcher
from .normalizer import normalize_many
from .source_manager import is_due, load_registry, status_after_failure

log = logging.getLogger("vestnio.ingestion")


@dataclass(slots=True)
class SourceRunResult:
    source_id: str
    ok: bool
    found: int = 0
    inserted: int = 0
    not_modified: bool = False
    skipped: bool = False
    error: str | None = None


def row_to_config(row: Source) -> SourceConfig:
    return SourceConfig(
        id=row.id,
        name=row.name,
        url=row.url,
        homepage=row.homepage,
        category=row.category,
        method=row.method,
        adapter=row.adapter,
        poll_minutes=row.poll_minutes,
        enabled=row.enabled,
        show_excerpt=row.show_excerpt,
        language=row.language,
        options=row.options or {},
    )


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        fetcher: Fetcher | None = None,
    ):
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.fetcher = fetcher or Fetcher(settings)
        self._sem = asyncio.Semaphore(settings.max_concurrent_fetches)
        self._running: set[str] = set()

    async def aclose(self) -> None:
        await self.fetcher.aclose()

    async def sync_registry(self) -> list[SourceConfig]:
        configs = load_registry(self.settings.sources_file)
        async with self.sessionmaker() as s:
            await repo.sync_sources(s, configs, self.settings.default_poll_minutes)
        log.info("source registry synced: %d sources", len(configs))
        return configs

    async def poll_all(self) -> list[SourceRunResult]:
        """Poll every enabled source once, concurrently (bounded)."""
        async with self.sessionmaker() as s:
            rows = [r for r in await repo.list_sources(s) if r.enabled]
        return list(await asyncio.gather(*(self.poll_source(r) for r in rows)))

    async def poll_due(self) -> list[SourceRunResult]:
        """Poll only the sources whose interval has elapsed (failing ones back off)."""
        now = datetime.now(timezone.utc)
        async with self.sessionmaker() as s:
            rows = [r for r in await repo.list_sources(s) if is_due(r, now)]
        return list(await asyncio.gather(*(self.poll_source(r) for r in rows)))

    async def poll_source_id(self, source_id: str) -> SourceRunResult | None:
        async with self.sessionmaker() as s:
            row = await repo.get_source(s, source_id)
        if row is None or not row.enabled or not row.in_registry:
            return None
        return await self.poll_source(row)

    async def poll_source(self, row: Source) -> SourceRunResult:
        if row.id in self._running:
            return SourceRunResult(row.id, ok=True, skipped=True)
        self._running.add(row.id)
        try:
            async with self._sem:
                return await self._poll(row)
        except Exception as exc:  # last-resort guard: never let one source kill the worker
            log.exception("unexpected error polling %s", row.id)
            return SourceRunResult(row.id, ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            self._running.discard(row.id)

    async def _enrich_new(self, articles: list) -> None:
        """Fetch og:image for *new* image-less articles (each page at most once)."""
        missing = [a for a in articles if not a.image_url]
        if not missing:
            return
        async with self.sessionmaker() as s:
            known = await repo.known_url_hashes(s, [a.url_hash for a in missing])
        fresh = [a for a in missing if a.url_hash not in known]
        if fresh:
            found = await enrich_images(fresh, self.fetcher)
            log.info("%s: preview images found for %d/%d new articles", fresh[0].source_id, found, min(len(fresh), 25))

    async def _poll(self, row: Source) -> SourceRunResult:
        started = datetime.now(timezone.utc)
        source = row_to_config(row)
        cache = adapters.CacheState(row.etag, row.last_modified)
        try:
            adapter = adapters.get_adapter(source)
            result = await adapter.fetch(source, self.fetcher, cache)
            articles = dedupe_batch(normalize_many(result.items, source))
            if source.options.get("enrich_images", source.method in (IngestionMethod.RSS, IngestionMethod.HTML)):
                await self._enrich_new(articles)
            async with self.sessionmaker() as s:
                inserted = await repo.insert_articles(s, articles)
                await repo.record_poll(
                    s,
                    row.id,
                    started_at=started,
                    ok=True,
                    status=SourceStatus.HEALTHY,
                    items_found=len(articles),
                    items_inserted=inserted,
                    not_modified=result.not_modified,
                    etag=result.cache.etag,
                    last_modified=result.cache.last_modified,
                )
            if result.not_modified:
                log.info("%s: 304 not modified", row.id)
            else:
                log.info("%s: %d items, %d new", row.id, len(articles), inserted)
            return SourceRunResult(row.id, True, len(articles), inserted, result.not_modified)
        except adapters.MissingCredentials as exc:
            msg = f"skipped: {exc}"
            log.warning("%s: %s", row.id, msg)
            async with self.sessionmaker() as s:
                await repo.record_poll(s, row.id, started_at=started, ok=False, status=SourceStatus.DISABLED, error=msg)
            return SourceRunResult(row.id, ok=False, error=msg)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            failures = (row.consecutive_failures or 0) + 1
            log.warning("%s: poll failed (%d in a row): %s", row.id, failures, msg)
            async with self.sessionmaker() as s:
                await repo.record_poll(
                    s, row.id, started_at=started, ok=False, status=status_after_failure(failures), error=msg
                )
            return SourceRunResult(row.id, ok=False, error=msg)
