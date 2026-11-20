"""Database Layer: all SQL used by the pipeline and the API lives here."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import Select, and_, delete, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..dedup import FINGERPRINT_WINDOW
from ..domain import NormalizedArticle, SourceConfig
from .models import Article, IngestionRun, Source

RUN_RETENTION = timedelta(days=7)
Sort = Literal["newest", "oldest", "relevance"]


# ======================================================================= sources
async def sync_sources(session: AsyncSession, configs: Sequence[SourceConfig], default_poll: int) -> None:
    """Upsert the registry into the `sources` table. Sources removed from the
    registry are kept (their articles stay readable) but flagged and disabled."""
    ids = [c.id for c in configs]
    for c in configs:
        values = dict(
            id=c.id,
            name=c.name,
            url=str(c.url),
            homepage=str(c.homepage) if c.homepage else None,
            category=c.category.value,
            method=c.method.value,
            adapter=c.adapter,
            poll_minutes=c.poll_minutes or default_poll,
            enabled=c.enabled,
            show_excerpt=c.show_excerpt,
            language=c.language,
            options=c.options,
            in_registry=True,
            origin="registry",
        )
        # a changed URL invalidates the stored HTTP cache validators
        await session.execute(
            update(Source)
            .where(Source.id == c.id, Source.url != str(c.url))
            .values(etag=None, last_modified=None)
        )
        stmt = pg_insert(Source).values(**values)
        set_ = {k: stmt.excluded[k] for k in values if k != "id"}
        # a channel the admin removed in the bot stays off, whatever sources.yaml says
        set_["enabled"] = and_(stmt.excluded.enabled, Source.admin_disabled.is_(False))
        stmt = stmt.on_conflict_do_update(index_elements=[Source.id], set_=set_)
        await session.execute(stmt)
    # Disabled-in-config sources show as "disabled"; re-enabled ones leave that state.
    await session.execute(
        update(Source).where(Source.enabled.is_(False)).values(status="disabled")
    )
    await session.execute(
        update(Source)
        .where(Source.enabled.is_(True), Source.status == "disabled", Source.id.in_(ids))
        .values(status="pending", consecutive_failures=0)
    )
    # Registry sources deleted from sources.yaml are switched off. Channels added
    # through the bot (origin='bot') are not part of the file and stay untouched.
    await session.execute(
        update(Source)
        .where(Source.id.not_in(ids), Source.origin == "registry")
        .values(in_registry=False, enabled=False, status="disabled")
    )
    await session.commit()


def _channel_url_match(username: str):
    return func.lower(Source.url) == f"https://t.me/s/{username.lower()}"


async def add_bot_channel(
    session: AsyncSession, *, username: str, title: str, category: str, added_by: int, default_poll: int
) -> tuple[Source, bool]:
    """Add a Telegram channel through the bot, or bring back one that was removed.
    Returns (source, added). An enabled channel already in VESTNIO is left as is."""
    # match by URL: registry ids differ from the username (tg-4pda for @pda_4)
    existing = await session.scalar(select(Source).where(_channel_url_match(username)).order_by(Source.enabled.desc()))
    if existing is not None:
        if existing.enabled:
            return existing, False
        existing.enabled, existing.admin_disabled = True, False
        existing.status, existing.consecutive_failures, existing.category = "pending", 0, category
        existing.in_registry = True
        await session.commit()
        return existing, True
    sid = f"tg-{username.lower()}"[:64]
    if await session.get(Source, sid) is not None:  # id taken by an unrelated source
        sid = f"tg-bot-{username.lower()}"[:64]
    src = Source(
        id=sid,
        name=title[:200] or f"@{username}",
        url=f"https://t.me/s/{username}",
        homepage=f"https://t.me/{username}",
        category=category,
        method="telegram",
        adapter=None,
        poll_minutes=default_poll,
        enabled=True,
        show_excerpt=True,
        language=None,
        options={},
        in_registry=True,
        origin="bot",
        added_by=added_by,
        status="pending",
        consecutive_failures=0,
    )
    session.add(src)
    await session.commit()
    return src, True


async def find_channel_source(session: AsyncSession, username: str) -> Source | None:
    """An *enabled* source for this Telegram channel, from sources.yaml or added via the bot."""
    return await session.scalar(select(Source).where(_channel_url_match(username), Source.enabled.is_(True)))


async def list_channels(session: AsyncSession) -> list[Source]:
    """All enabled Telegram channels, whichever way they were added."""
    stmt = (
        select(Source)
        .where(Source.method == "telegram", Source.enabled.is_(True))
        .order_by(Source.category, func.lower(Source.name))
    )
    return list((await session.scalars(stmt)).all())


async def disable_channel(session: AsyncSession, username: str) -> Source | None:
    """Remove one Telegram channel from VESTNIO (any origin). Its articles disappear
    from the feed; registry syncs keep it off until it's added again via the bot."""
    src = await find_channel_source(session, username)
    if src is None:
        return None
    src.enabled, src.admin_disabled, src.status = False, True, "disabled"
    await session.commit()
    return src


def channel_username(source: Source) -> str:
    return source.url.rstrip("/").rsplit("/", 1)[-1]


async def list_sources(session: AsyncSession, *, only_registry: bool = True) -> list[Source]:
    stmt = select(Source).order_by(Source.category, Source.name)
    if only_registry:
        stmt = stmt.where(Source.in_registry.is_(True))
    return list((await session.scalars(stmt)).all())


async def get_source(session: AsyncSession, source_id: str) -> Source | None:
    return await session.get(Source, source_id)


async def article_counts_by_source(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Article.source_id, func.count()).group_by(Article.source_id))
    return {sid: n for sid, n in rows.all()}


async def record_poll(
    session: AsyncSession,
    source_id: str,
    *,
    started_at: datetime,
    ok: bool,
    status: str,
    items_found: int = 0,
    items_inserted: int = 0,
    not_modified: bool = False,
    error: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    values: dict = dict(last_polled_at=now, status=status, updated_at=now)
    if ok:
        values.update(
            consecutive_failures=0,
            last_success_at=now,
            last_error=None,
            etag=etag,
            last_modified=last_modified,
        )
        if not not_modified:
            values["last_item_count"] = items_found
    else:
        values.update(consecutive_failures=Source.consecutive_failures + 1, last_error=(error or "")[:2000])
    await session.execute(update(Source).where(Source.id == source_id).values(**values))
    session.add(
        IngestionRun(
            source_id=source_id,
            started_at=started_at,
            finished_at=now,
            ok=ok,
            not_modified=not_modified,
            items_found=items_found,
            items_inserted=items_inserted,
            error=error[:2000] if error else None,
        )
    )
    await session.commit()


async def recent_runs(session: AsyncSession, source_id: str, limit: int = 20) -> list[IngestionRun]:
    stmt = (
        select(IngestionRun)
        .where(IngestionRun.source_id == source_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def prune_runs(session: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - RUN_RETENTION
    res = await session.execute(delete(IngestionRun).where(IngestionRun.started_at < cutoff))
    await session.commit()
    return res.rowcount or 0


# ====================================================================== articles
async def _known_fingerprints(session: AsyncSession, fps: set[str]) -> set[str]:
    if not fps:
        return set()
    since = datetime.now(timezone.utc) - FINGERPRINT_WINDOW
    rows = await session.scalars(
        select(Article.title_fp).where(Article.title_fp.in_(fps), Article.published_at >= since)
    )
    return set(rows.all())


async def known_url_hashes(session: AsyncSession, hashes: Sequence[str]) -> set[str]:
    if not hashes:
        return set()
    rows = await session.scalars(select(Article.url_hash).where(Article.url_hash.in_(list(hashes))))
    return set(rows.all())


async def insert_articles(session: AsyncSession, articles: Sequence[NormalizedArticle]) -> int:
    """Insert new articles. Duplicates are skipped by all three rules (GUID, canonical
    URL via unique constraints; title fingerprint via a lookup in the 72h window).
    Returns the number of rows actually inserted."""
    if not articles:
        return 0
    known_fps = await _known_fingerprints(session, {a.title_fp for a in articles if a.title_fp})
    rows = [
        dict(
            source_id=a.source_id,
            category=a.category.value,
            external_id=a.external_id,
            title=a.title,
            summary=a.summary,
            image_url=a.image_url,
            url=a.url,
            canonical_url=a.canonical_url,
            url_hash=a.url_hash,
            published_at=a.published_at,
            published_estimated=a.published_estimated,
            language=a.language,
            title_fp=a.title_fp,
        )
        for a in articles
        if not (a.title_fp and a.title_fp in known_fps)
    ]
    if not rows:
        return 0
    stmt = pg_insert(Article).values(rows).on_conflict_do_nothing().returning(Article.id)
    inserted = len((await session.execute(stmt)).all())
    await session.commit()
    return inserted


class InvalidCursor(ValueError):
    pass


def encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, sort: Sort) -> dict:
    try:
        raw = base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode())
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("s") != sort:
            raise ValueError("cursor belongs to another sort order")
        if sort == "relevance":
            data["o"] = int(data["o"])
            if data["o"] < 0:
                raise ValueError("negative offset")
        else:
            data["t"] = datetime.fromisoformat(data["t"])
            data["i"] = int(data["i"])
        return data
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("malformed or mismatched cursor") from exc


_TERM = re.compile(r"\w+", re.UNICODE)


def build_tsquery(q: str | None) -> str | None:
    """User text -> safe prefix tsquery ('nint:* & swit:*'). Only word characters
    survive, so tsquery operators in user input can't break the query."""
    if not q:
        return None
    terms = _TERM.findall(q.casefold())[:8]
    return " & ".join(f"{t}:*" for t in terms) or None


@dataclass(slots=True)
class ArticleQuery:
    category: str | None = None
    source_ids: Sequence[str] | None = None
    q: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    has_image: bool | None = None
    sort: Sort = "newest"
    cursor: str | None = None
    limit: int = 20


async def query_articles(
    session: AsyncSession, q: ArticleQuery
) -> tuple[list[tuple[Article, Source]], str | None]:
    stmt: Select = select(Article, Source).join(Source, Source.id == Article.source_id)
    conds = [Source.enabled.is_(True)]  # switched-off sources disappear from the feed
    if q.category:
        conds.append(Article.category == q.category)
    if q.source_ids:
        conds.append(Article.source_id.in_(list(q.source_ids)))
    if q.since:
        conds.append(Article.published_at >= q.since)
    if q.until:
        conds.append(Article.published_at < q.until)
    if q.has_image is True:
        conds.append(Article.image_url.is_not(None))
    elif q.has_image is False:
        conds.append(Article.image_url.is_(None))

    tsq = build_tsquery(q.q)
    ts_query = func.to_tsquery(text("'simple'::regconfig"), tsq) if tsq else None
    if ts_query is not None:
        conds.append(Article.search_vector.op("@@")(ts_query))

    sort: Sort = q.sort if (q.sort != "relevance" or ts_query is not None) else "newest"
    cur = decode_cursor(q.cursor, sort) if q.cursor else None
    offset = 0

    if sort == "newest":
        if cur:
            conds.append(tuple_(Article.published_at, Article.id) < tuple_(cur["t"], cur["i"]))
        order = (Article.published_at.desc(), Article.id.desc())
    elif sort == "oldest":
        if cur:
            conds.append(tuple_(Article.published_at, Article.id) > tuple_(cur["t"], cur["i"]))
        order = (Article.published_at.asc(), Article.id.asc())
    else:  # relevance: rank is not a stable keyset, so the cursor carries an offset
        offset = cur["o"] if cur else 0
        order = (func.ts_rank_cd(Article.search_vector, ts_query).desc(), Article.published_at.desc(), Article.id.desc())

    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(*order).offset(offset).limit(q.limit + 1)

    rows = [(r[0], r[1]) for r in (await session.execute(stmt)).all()]
    next_cursor = None
    if len(rows) > q.limit:
        rows = rows[: q.limit]
        last = rows[-1][0]
        if sort == "relevance":
            next_cursor = encode_cursor({"s": sort, "o": offset + q.limit})
        else:
            next_cursor = encode_cursor({"s": sort, "t": last.published_at.isoformat(), "i": last.id})
    return rows, next_cursor


async def get_article(session: AsyncSession, article_id: int) -> tuple[Article, Source] | None:
    row = (
        await session.execute(
            select(Article, Source).join(Source, Source.id == Article.source_id).where(Article.id == article_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def category_stats(session: AsyncSession) -> dict[str, dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = await session.execute(
        select(
            Article.category,
            func.count(),
            func.count().filter(Article.published_at >= since),
            func.max(Article.published_at),
        )
        .join(Source, Source.id == Article.source_id)
        .where(Source.enabled.is_(True))
        .group_by(Article.category)
    )
    return {cat: {"total": n, "last_24h": n24, "latest": latest} for cat, n, n24, latest in rows.all()}


async def health_stats(session: AsyncSession) -> dict:
    await session.execute(select(1))
    total = await session.scalar(select(func.count()).select_from(Article))
    latest_fetch = await session.scalar(select(func.max(Source.last_success_at)))
    by_status = dict(
        (await session.execute(
            select(Source.status, func.count()).where(Source.in_registry.is_(True)).group_by(Source.status)
        )).all()
    )
    return {"articles": total or 0, "last_successful_fetch": latest_fetch, "sources_by_status": by_status}
