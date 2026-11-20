"""Command line tools.

    python -m vestnio.cli check            # fetch + parse every source, no database (validates the registry)
    python -m vestnio.cli check bbc-world  # just one source
    python -m vestnio.cli ingest           # one ingestion pass into the database (all enabled sources)
    python -m vestnio.cli sources          # show source status from the database
    python -m vestnio.cli backfill-images  # og:image for recent articles that have no picture

The scheduled, long-running collector is `python -m vestnio.worker`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from . import adapters
from .config import get_settings
from .dedup import dedupe_batch
from .fetcher import Fetcher
from .normalizer import normalize_many
from .source_manager import load_registry


async def cmd_check(only: list[str]) -> int:
    settings = get_settings()
    configs = [c for c in load_registry(settings.sources_file) if not only or c.id in only]
    failures = 0
    async with Fetcher(settings) as fetcher:

        async def one(cfg):
            t0 = time.perf_counter()
            if not cfg.enabled and not only:
                return cfg, None, "disabled in registry", 0.0
            try:
                res = await adapters.get_adapter(cfg).fetch(cfg, fetcher, adapters.CacheState())
                arts = dedupe_batch(normalize_many(res.items, cfg))
                return cfg, arts, None, time.perf_counter() - t0
            except Exception as exc:  # report, continue with the other sources
                return cfg, None, f"{type(exc).__name__}: {exc}", time.perf_counter() - t0

        results = await asyncio.gather(*(one(c) for c in configs))

    for cfg, arts, err, dt in results:
        if err == "disabled in registry":
            print(f"  SKIP  {cfg.id:<22} {cfg.method.value:<5} {err}")
            continue
        if err:
            failures += 1
            print(f"  FAIL  {cfg.id:<22} {cfg.method.value:<5} {err}")
            continue
        assert arts is not None
        with_img = sum(1 for a in arts if a.image_url)
        with_sum = sum(1 for a in arts if a.summary)
        dated = sum(1 for a in arts if not a.published_estimated)
        newest = max((a.published_at for a in arts), default=None)
        print(
            f"  OK    {cfg.id:<22} {cfg.method.value:<5} {len(arts):>3} items  "
            f"img {with_img:>3}  desc {with_sum:>3}  dated {dated:>3}  "
            f"newest {newest:%Y-%m-%d %H:%M}Z  {dt:4.1f}s" if newest else f"  OK    {cfg.id:<22} 0 items"
        )
        if arts:
            print(f"        └ {arts[0].title[:100]}")
    print(f"\n{len(results) - failures}/{len(results)} sources OK")
    return 1 if failures else 0


async def cmd_ingest() -> int:
    from .db import dispose_engine, get_sessionmaker
    from .ingestion import IngestionService

    service = IngestionService(get_settings(), get_sessionmaker())
    try:
        await service.sync_registry()
        results = await service.poll_all()
    finally:
        await service.aclose()
        await dispose_engine()
    for r in sorted(results, key=lambda r: r.source_id):
        state = "OK  " if r.ok else "FAIL"
        detail = "not modified" if r.not_modified else f"{r.found} found, {r.inserted} new"
        print(f"  {state} {r.source_id:<22} {r.error or detail}")
    return 0 if any(r.ok for r in results) else 1


async def cmd_backfill_images(hours: int, limit: int) -> int:
    """Look up og:image for recent image-less articles from RSS/HTML sources."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update

    from .db import dispose_engine, get_sessionmaker
    from .db.models import Article, Source
    from .domain import NormalizedArticle
    from .enrich import enrich_images

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    sm = get_sessionmaker()
    async with sm() as s:
        rows = (
            await s.execute(
                select(Article)
                .join(Source, Source.id == Article.source_id)
                .where(
                    Article.image_url.is_(None),
                    Article.published_at >= since,
                    Source.enabled.is_(True),
                    Source.method.in_(["rss", "html"]),
                )
                .order_by(Article.published_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    shells = [
        NormalizedArticle(r.source_id, r.category, r.external_id, r.title, r.summary, None, r.url,
                          r.canonical_url, r.url_hash, r.published_at, r.published_estimated)
        for r in rows
    ]
    async with Fetcher(get_settings()) as f:
        found = await enrich_images(shells, f, limit=limit, concurrency=6)
    async with sm() as s:
        for a in shells:
            if a.image_url:
                await s.execute(update(Article).where(Article.url_hash == a.url_hash).values(image_url=a.image_url))
        await s.commit()
    await dispose_engine()
    print(f"preview images found for {found}/{len(shells)} articles")
    return 0


async def cmd_sources() -> int:
    from .db import dispose_engine, get_sessionmaker
    from .db import repository as repo

    async with get_sessionmaker()() as s:
        rows = await repo.list_sources(s)
        counts = await repo.article_counts_by_source(s)
    await dispose_engine()
    for r in rows:
        print(
            f"  {r.id:<22} {r.category:<11} {r.status:<9} fails={r.consecutive_failures} "
            f"articles={counts.get(r.id, 0):<5} last_ok={r.last_success_at:%Y-%m-%d %H:%M}"
            if r.last_success_at
            else f"  {r.id:<22} {r.category:<11} {r.status:<9} fails={r.consecutive_failures} {r.last_error or ''}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vestnio")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="fetch and parse sources without touching the database")
    p_check.add_argument("ids", nargs="*")
    sub.add_parser("ingest", help="run one ingestion pass into the database")
    sub.add_parser("sources", help="show source status")
    p_bf = sub.add_parser("backfill-images", help="fetch og:image for recent articles without a picture")
    p_bf.add_argument("--hours", type=int, default=48)
    p_bf.add_argument("--limit", type=int, default=400)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if args.cmd == "check":
        return asyncio.run(cmd_check(args.ids))
    if args.cmd == "ingest":
        return asyncio.run(cmd_ingest())
    if args.cmd == "backfill-images":
        return asyncio.run(cmd_backfill_images(args.hours, args.limit))
    return asyncio.run(cmd_sources())


if __name__ == "__main__":
    raise SystemExit(main())
