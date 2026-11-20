"""Public API.

    GET  /api/v1/articles          feed: search, filters, sorting, cursor pagination
    GET  /api/v1/articles/{id}     single article
    GET  /api/v1/categories        categories with counts
    GET  /api/v1/sources           source registry with operational status
    GET  /api/v1/health            liveness + ingestion freshness
    POST /api/v1/admin/sources/{id}/refresh   (Telegram initData of an admin required)
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import Settings, get_settings
from ..db import dispose_engine, get_session, get_sessionmaker
from ..db import repository as repo
from ..domain import Category
from ..bot_replies import build_reply
from ..telegram_auth import InitData, InitDataError, validate_init_data
from .schemas import (
    ArticleDetailOut,
    ArticleOut,
    CategoryOut,
    Envelope,
    ErrorEnvelope,
    HealthOut,
    ListMeta,
    SourceOut,
    SourceRef,
)

log = logging.getLogger("vestnio.api")

FEED_CACHE = "public, max-age=30, stale-while-revalidate=120"
META_CACHE = "public, max-age=60, stale-while-revalidate=300"
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ----------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _error(status: int, code: str, message: str, details: list | None = None, headers=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or e["loc"][0], "message": e["msg"]}
            for e in exc.errors()
        ]
        return _error(422, "validation_error", "Invalid request parameters", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        return _error(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError):
        log.error("database error: %s", exc)
        return _error(503, "database_unavailable", "The news database is temporarily unavailable")


# ------------------------------------------------------------------ mapping
def _article_out(a, s, detail: bool = False) -> ArticleOut:
    data = dict(
        id=a.id,
        title=a.title,
        summary=a.summary if s.show_excerpt else None,
        image_url=a.image_url,
        url=a.url,
        published_at=a.published_at,
        published_estimated=a.published_estimated,
        language=a.language,
        category=a.category,
        source=SourceRef(id=s.id, name=s.name, homepage=s.homepage),
    )
    if detail:
        return ArticleDetailOut(**data, canonical_url=a.canonical_url, fetched_at=a.fetched_at)
    return ArticleOut(**data)


# --------------------------------------------------------------------- auth
async def require_admin(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> InitData:
    """`Authorization: tma <Telegram.WebApp.initData>`; the user must be in VESTNIO_ADMIN_IDS."""
    settings: Settings = request.app.state.settings
    if not settings.bot_token:
        raise ApiError(503, "auth_unavailable", "Telegram authentication is not configured")
    if not authorization or not authorization.startswith("tma "):
        raise ApiError(401, "unauthorized", "Telegram initData required")
    try:
        data = validate_init_data(
            authorization[4:], settings.bot_token.get_secret_value(), settings.init_data_max_age_seconds
        )
    except InitDataError as exc:
        raise ApiError(401, "unauthorized", str(exc)) from exc
    if not data.user or data.user.id not in settings.admin_ids:
        raise ApiError(403, "forbidden", "Administrator access required")
    return data


# ---------------------------------------------------------------------- app
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if app.state.ingestion is not None:
            await app.state.ingestion.aclose()
        await dispose_engine()

    app = FastAPI(
        title="VESTNIO API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        responses={422: {"model": ErrorEnvelope}},
    )
    app.state.settings = settings
    app.state.ingestion = None  # created lazily by the admin refresh endpoint
    _install_error_handlers(app)
    app.add_middleware(GZipMiddleware, minimum_size=800)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/api/v1/articles", response_model=Envelope[list[ArticleOut]])
    async def list_articles(
        response: Response,
        session: SessionDep,
        category: Category | None = None,
        source: Annotated[list[str] | None, Query(description="source id; repeat or comma-separate")] = None,
        q: Annotated[str | None, Query(max_length=200, description="full-text search in headlines and summaries")] = None,
        sort: Literal["newest", "oldest", "relevance"] = "newest",
        since: datetime | None = None,
        until: datetime | None = None,
        has_image: bool | None = None,
        cursor: Annotated[str | None, Query(max_length=500)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ):
        source_ids = [p.strip() for v in (source or []) for p in v.split(",") if p.strip()] or None
        if source_ids and len(source_ids) > 50:
            raise ApiError(422, "validation_error", "Too many sources", [{"field": "source", "message": "max 50"}])
        for name, value in (("since", since), ("until", until)):
            if value is not None and value.tzinfo is None:
                raise ApiError(422, "validation_error", f"'{name}' must include a timezone", [{"field": name, "message": "use ISO 8601 with Z or offset"}])
        query = repo.ArticleQuery(
            category=category.value if category else None,
            source_ids=source_ids,
            q=q.strip() if q else None,
            since=since,
            until=until,
            has_image=has_image,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
        try:
            rows, next_cursor = await repo.query_articles(session, query)
        except repo.InvalidCursor as exc:
            raise ApiError(400, "invalid_cursor", str(exc)) from exc
        response.headers["Cache-Control"] = FEED_CACHE
        effective_sort = sort if (sort != "relevance" or repo.build_tsquery(query.q)) else "newest"
        return Envelope(
            data=[_article_out(a, s) for a, s in rows],
            meta=ListMeta(count=len(rows), limit=limit, next_cursor=next_cursor, sort=effective_sort),
        )

    @app.get("/api/v1/articles/{article_id}", response_model=Envelope[ArticleDetailOut])
    async def get_article(
        response: Response, session: SessionDep, article_id: Annotated[int, PathParam(ge=1, le=2**62)]
    ):
        row = await repo.get_article(session, article_id)
        if row is None:
            raise ApiError(404, "not_found", f"Article {article_id} not found")
        response.headers["Cache-Control"] = "public, max-age=300"
        return Envelope(data=_article_out(*row, detail=True))

    @app.get("/api/v1/categories", response_model=Envelope[list[CategoryOut]])
    async def list_categories(response: Response, session: SessionDep):
        stats = await repo.category_stats(session)
        sources = await repo.list_sources(session)
        out = []
        for cat in Category:
            st = stats.get(cat.value, {})
            out.append(
                CategoryOut(
                    id=cat.value,
                    label=cat.label,
                    article_count=st.get("total", 0),
                    last_24h=st.get("last_24h", 0),
                    source_count=sum(1 for s in sources if s.category == cat.value and s.enabled),
                    latest_published_at=st.get("latest"),
                )
            )
        response.headers["Cache-Control"] = META_CACHE
        return Envelope(data=out, meta=ListMeta(count=len(out)))

    @app.get("/api/v1/sources", response_model=Envelope[list[SourceOut]])
    async def list_sources(response: Response, session: SessionDep, category: Category | None = None):
        rows = await repo.list_sources(session)
        counts = await repo.article_counts_by_source(session)
        out = [
            SourceOut(
                id=r.id,
                name=r.name,
                homepage=r.homepage,
                category=r.category,
                method=r.method,
                enabled=r.enabled,
                status=r.status,
                poll_minutes=r.poll_minutes,
                last_success_at=r.last_success_at,
                last_polled_at=r.last_polled_at,
                last_error=(r.last_error or "")[:300] or None,
                article_count=counts.get(r.id, 0),
            )
            for r in rows
            if category is None or r.category == category.value
        ]
        response.headers["Cache-Control"] = META_CACHE
        return Envelope(data=out, meta=ListMeta(count=len(out)))

    @app.get("/api/v1/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
    async def health(response: Response):
        response.headers["Cache-Control"] = "no-store"
        try:
            async with get_sessionmaker()() as session:
                stats = await repo.health_stats(session)
        except (SQLAlchemyError, OSError) as exc:
            log.error("health: database unavailable: %s", exc)
            response.status_code = 503
            return HealthOut(status="down", database="unavailable", articles=0, last_successful_fetch=None, sources={}, version=__version__)
        last = stats["last_successful_fetch"]
        stale = last is None or (datetime.now(timezone.utc) - last).total_seconds() > 3 * 3600
        healthy = stats["sources_by_status"].get("healthy", 0)
        return HealthOut(
            status="degraded" if stale or healthy == 0 else "ok",
            database="ok",
            articles=stats["articles"],
            last_successful_fetch=last,
            sources=stats["sources_by_status"],
            version=__version__,
        )

    @app.post("/api/v1/admin/sources/{source_id}/refresh")
    async def admin_refresh(source_id: str, request: Request, admin: InitData = Depends(require_admin)):
        from ..ingestion import IngestionService

        if request.app.state.ingestion is None:
            request.app.state.ingestion = IngestionService(settings, get_sessionmaker())
        result = await request.app.state.ingestion.poll_source_id(source_id)
        if result is None:
            raise ApiError(404, "not_found", f"Source {source_id} not found or disabled")
        log.info("admin %s refreshed %s", admin.user.id if admin.user else "?", source_id)
        return {"data": {"source_id": source_id, "ok": result.ok, "found": result.found, "inserted": result.inserted, "error": result.error}}

    @app.post("/api/telegram/webhook", include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ):
        """Webhook mode for serverless hosting: Telegram POSTs updates here."""
        secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else ""
        if not secret or not settings.bot_token:
            raise ApiError(404, "not_found", "Unknown API endpoint")
        if not hmac.compare_digest(x_telegram_bot_api_secret_token or "", secret):
            raise ApiError(403, "forbidden", "Bad webhook secret")
        try:
            update = await request.json()
            reply = build_reply(update, settings.webapp_url or "")
            if reply:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{settings.bot_token.get_secret_value()}/sendMessage", json=reply
                    )
        except Exception:  # always 200, or Telegram re-delivers the same update forever
            log.exception("webhook update failed")
        return {"ok": True}

    @app.get("/api/{rest:path}", include_in_schema=False)
    async def api_not_found(rest: str):
        raise ApiError(404, "not_found", "Unknown API endpoint")

    if settings.serve_webapp_dir:
        _mount_webapp(app, Path(settings.serve_webapp_dir))
    return app


def _mount_webapp(app: FastAPI, root: Path) -> None:
    """Serve the built Mini App (single-page app with history routing)."""
    index = root / "index.html"
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
