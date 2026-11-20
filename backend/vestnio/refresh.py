"""Self-refresh for serverless hosting.

The scheduled collector (GitHub Actions / the APScheduler worker) is the primary way
news gets in. As a safety net — GitHub cron runs can be late or silently skipped —
the API starts a collection in the background when someone reads the feed and the
newest successful poll is older than STALE_AFTER.

A PostgreSQL advisory lock makes sure only one collection runs at a time across all
function instances; a short in-process cooldown avoids even asking for it on every request.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from .config import Settings
from .db import get_sessionmaker
from .db.models import Source
from .fetcher import Fetcher
from .ingestion import IngestionService

log = logging.getLogger("vestnio.refresh")

STALE_AFTER = timedelta(minutes=15)
LOCK_KEY = 0x56455354  # "VEST"
_COOLDOWN_SECONDS = 60
_last_check = 0.0


async def refresh_if_stale(settings: Settings) -> bool:
    """Collect due sources if the feed is stale. Returns True if a collection ran."""
    global _last_check
    if time.monotonic() - _last_check < _COOLDOWN_SECONDS:
        return False
    _last_check = time.monotonic()

    sm = get_sessionmaker()
    async with sm() as s:
        newest = await s.scalar(
            select(func.max(Source.last_polled_at)).where(Source.enabled.is_(True), Source.in_registry.is_(True))
        )
    if newest is not None and datetime.now(timezone.utc) - newest < STALE_AFTER:
        return False

    # hold one connection for the lock for the whole run
    async with sm() as lock_session:
        got = await lock_session.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})
        if not got:
            return False  # another instance (or the cron job) is already collecting
        try:
            async with Fetcher(settings) as fetcher:
                results = await IngestionService(settings, sm, fetcher).poll_due()
            ok = sum(1 for r in results if r.ok)
            new = sum(r.inserted for r in results)
            log.info("self-refresh: %d/%d sources ok, %d new articles", ok, len(results), new)
            return True
        except Exception:
            log.exception("self-refresh failed")
            return False
        finally:
            await lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await lock_session.commit()
