"""Dedicated ingestion worker (APScheduler).

    python -m vestnio.worker

* one interval job per source, using the source's own poll_minutes (default 15)
* failing sources back off exponentially (see source_manager.next_poll_at)
* the registry file is re-read every few minutes; added/removed/changed sources
  are rescheduled without a restart
* ingestion-run log is pruned daily
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .db import dispose_engine, get_sessionmaker
from .db import repository as repo
from .ingestion import IngestionService
from .source_manager import RegistryError, is_due

log = logging.getLogger("vestnio.worker")

REGISTRY_RELOAD_MINUTES = 5


class IngestionWorker:
    def __init__(self, service: IngestionService):
        self.service = service
        self.scheduler = AsyncIOScheduler(
            timezone=timezone.utc,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )
        self._intervals: dict[str, int] = {}

    async def start(self) -> None:
        await self.reload_registry(first_run=True)
        self.scheduler.add_job(
            self.reload_registry, IntervalTrigger(minutes=REGISTRY_RELOAD_MINUTES), id="registry-reload"
        )
        self.scheduler.add_job(self._prune, IntervalTrigger(hours=24), id="prune-runs")
        self.scheduler.start()
        log.info("worker started with %d source jobs", len(self._intervals))

    async def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        await self.service.aclose()

    async def reload_registry(self, first_run: bool = False) -> None:
        try:
            await self.service.sync_registry()
        except RegistryError as exc:
            log.error("registry not reloaded, keeping current schedule: %s", exc)
            if first_run:
                raise
            return
        async with self.service.sessionmaker() as s:
            rows = [r for r in await repo.list_sources(s) if r.enabled]

        wanted = {r.id: r.poll_minutes for r in rows}
        for sid in set(self._intervals) - set(wanted):
            self.scheduler.remove_job(f"source:{sid}")
            del self._intervals[sid]
            log.info("unscheduled %s", sid)

        now = datetime.now(timezone.utc)
        for i, row in enumerate(rows):
            if self._intervals.get(row.id) == row.poll_minutes:
                continue
            # first poll: immediately for never-polled / overdue sources, staggered 2s apart
            first = now + timedelta(seconds=2 * i)
            if row.last_polled_at and not is_due(row, now):
                first = max(first, row.last_polled_at + timedelta(minutes=row.poll_minutes))
            self.scheduler.add_job(
                self._poll_job,
                IntervalTrigger(minutes=row.poll_minutes, jitter=20),
                args=[row.id],
                id=f"source:{row.id}",
                replace_existing=True,
                next_run_time=first,
            )
            self._intervals[row.id] = row.poll_minutes
            log.info("scheduled %s every %d min (first run %s)", row.id, row.poll_minutes, first.strftime("%H:%M:%S"))

    async def _poll_job(self, source_id: str) -> None:
        async with self.service.sessionmaker() as s:
            row = await repo.get_source(s, source_id)
        if row is None or not row.enabled:
            return
        # Healthy sources run on every tick; failing ones skip ticks (exponential backoff).
        slack = timedelta(minutes=row.poll_minutes / 2)
        if not is_due(row, datetime.now(timezone.utc) + slack):
            log.info("%s: backing off after %d failures", source_id, row.consecutive_failures)
            return
        await self.service.poll_source(row)

    async def _prune(self) -> None:
        async with self.service.sessionmaker() as s:
            n = await repo.prune_runs(s)
        log.info("pruned %d old ingestion runs", n)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs may carry API keys
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # one line per job run is noise
    worker = IngestionWorker(IngestionService(settings, get_sessionmaker()))
    await worker.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await worker.stop()
        await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
