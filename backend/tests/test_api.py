import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr

from vestnio.api.app import create_app
from vestnio.db import repository as repo
from vestnio.domain import RawItem, SourceConfig
from vestnio.normalizer import normalize
from vestnio.telegram_auth import sign_init_data

from .conftest import requires_db

pytestmark = requires_db
UTC = timezone.utc
NOW = datetime.now(UTC).replace(microsecond=0)

SOURCES = [
    SourceConfig(id="world-a", name="World A", url="https://wa.example/rss", category="world", method="rss"),
    SourceConfig(id="games-b", name="Games B", url="https://gb.example/rss", category="gaming", method="rss"),
    SourceConfig(id="tech-c", name="Tech C", url="https://tc.example/rss", category="technology", method="rss", show_excerpt=False),
]

TITLES = {
    "world-a": ["Summit ends with climate agreement", "Election results announced in capital", "Flood warnings issued for coastal towns"],
    "games-b": ["Nintendo Switch successor gets release date", "Indie platformer tops sales charts", "Studio announces sequel to beloved RPG"],
    "tech-c": ["New chip doubles laptop battery life", "Browser update patches critical flaw", "Open source database hits version two"],
}


@pytest.fixture
async def client(sessionmaker, settings):
    async with sessionmaker() as s:
        await repo.sync_sources(s, SOURCES, 15)
        n = 0
        for src in SOURCES:
            arts = []
            for i, title in enumerate(TITLES[src.id]):
                n += 1
                arts.append(
                    normalize(
                        RawItem(
                            title=title,
                            url=f"https://{src.id}.example/a/{i}",
                            external_id=f"{src.id}-{i}",
                            summary=f"Teaser for {title.lower()} with switch keyword" if "Switch" in title else f"Teaser {n}",
                            image_url=f"https://img.example/{n}.jpg" if i % 2 == 0 else None,
                            published=NOW - timedelta(hours=n),
                        ),
                        src,
                    )
                )
            await repo.insert_articles(s, arts)
    settings.bot_token = SecretStr("123456:TEST-TOKEN")
    settings.admin_ids = [42]
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_feed_is_chronological_with_envelope(client):
    r = await client.get("/api/v1/articles")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"data", "meta"}
    times = [a["published_at"] for a in body["data"]]
    assert len(times) == 9 and times == sorted(times, reverse=True)
    assert all(t.endswith("Z") for t in times)
    first = body["data"][0]
    assert {"id", "title", "summary", "image_url", "url", "published_at", "language", "category", "source"} <= set(first)
    assert "public" in r.headers["cache-control"]


async def test_cursor_pagination_walks_everything_once(client):
    seen, cursor = [], None
    while True:
        r = await client.get("/api/v1/articles", params={"limit": 4, **({"cursor": cursor} if cursor else {})})
        body = r.json()
        seen += [a["id"] for a in body["data"]]
        cursor = body["meta"]["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 9 and len(set(seen)) == 9


async def test_oldest_sort_and_pagination(client):
    r1 = (await client.get("/api/v1/articles", params={"sort": "oldest", "limit": 5})).json()
    r2 = (await client.get("/api/v1/articles", params={"sort": "oldest", "limit": 5, "cursor": r1["meta"]["next_cursor"]})).json()
    times = [a["published_at"] for a in r1["data"] + r2["data"]]
    assert len(times) == 9 and times == sorted(times)


async def test_category_and_source_filters(client):
    r = (await client.get("/api/v1/articles", params={"category": "gaming"})).json()
    assert {a["category"] for a in r["data"]} == {"gaming"} and len(r["data"]) == 3
    r = (await client.get("/api/v1/articles", params={"source": "world-a,tech-c"})).json()
    assert {a["source"]["id"] for a in r["data"]} == {"world-a", "tech-c"}
    r = (await client.get("/api/v1/articles", params=[("source", "world-a"), ("source", "games-b"), ("has_image", "true")])).json()
    assert all(a["image_url"] for a in r["data"])


async def test_full_text_search_titles_summaries_and_prefix(client):
    r = (await client.get("/api/v1/articles", params={"q": "nintendo"})).json()
    assert [a["title"] for a in r["data"]] == ["Nintendo Switch successor gets release date"]
    r = (await client.get("/api/v1/articles", params={"q": "batt"})).json()  # prefix match
    assert r["data"][0]["title"] == "New chip doubles laptop battery life"
    r = (await client.get("/api/v1/articles", params={"q": "keyword"})).json()  # summary match
    assert len(r["data"]) == 1
    r = (await client.get("/api/v1/articles", params={"q": "switch release", "sort": "relevance"})).json()
    assert r["meta"]["sort"] == "relevance" and r["data"][0]["title"].startswith("Nintendo")
    r = (await client.get("/api/v1/articles", params={"q": "a & | ! :* ("})).json()  # operator junk is harmless
    assert "data" in r


async def test_excerpt_hidden_when_not_permitted(client):
    r = (await client.get("/api/v1/articles", params={"source": "tech-c"})).json()
    assert all(a["summary"] is None for a in r["data"])


async def test_article_detail_and_404(client):
    first = (await client.get("/api/v1/articles", params={"limit": 1})).json()["data"][0]
    r = await client.get(f"/api/v1/articles/{first['id']}")
    assert r.status_code == 200
    assert r.json()["data"]["canonical_url"].startswith("https://")
    r = await client.get("/api/v1/articles/987654")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "params, status, code",
    [
        ({"category": "sports"}, 422, "validation_error"),
        ({"limit": 0}, 422, "validation_error"),
        ({"limit": 500}, 422, "validation_error"),
        ({"sort": "random"}, 422, "validation_error"),
        ({"since": "2026-11-19T10:00:00"}, 422, "validation_error"),  # naive datetime
        ({"cursor": "not-a-cursor"}, 400, "invalid_cursor"),
        ({"q": "x" * 201}, 422, "validation_error"),
    ],
)
async def test_input_validation(client, params, status, code):
    r = await client.get("/api/v1/articles", params=params)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


async def test_cursor_from_other_sort_rejected(client):
    cur = (await client.get("/api/v1/articles", params={"limit": 2})).json()["meta"]["next_cursor"]
    r = await client.get("/api/v1/articles", params={"limit": 2, "sort": "oldest", "cursor": cur})
    assert r.status_code == 400


async def test_categories(client):
    r = (await client.get("/api/v1/categories")).json()
    cats = {c["id"]: c for c in r["data"]}
    assert set(cats) == {"gaming", "world", "technology"}
    assert cats["gaming"]["article_count"] == 3 and cats["gaming"]["source_count"] == 1
    assert cats["world"]["label"] == "World News"


async def test_disabled_source_is_hidden_from_feed(client, sessionmaker):
    async with sessionmaker() as s:
        await repo.sync_sources(s, [*SOURCES[:2], SOURCES[2].model_copy(update={"enabled": False})], 15)
    r = (await client.get("/api/v1/articles")).json()
    assert len(r["data"]) == 6 and "tech-c" not in {a["source"]["id"] for a in r["data"]}
    cats = {c["id"]: c for c in (await client.get("/api/v1/categories")).json()["data"]}
    assert cats["technology"]["article_count"] == 0


async def test_sources(client):
    r = (await client.get("/api/v1/sources")).json()
    assert {s["id"] for s in r["data"]} == {"world-a", "games-b", "tech-c"}
    assert all(s["article_count"] == 3 and s["status"] == "pending" for s in r["data"])
    r = (await client.get("/api/v1/sources", params={"category": "gaming"})).json()
    assert [s["id"] for s in r["data"]] == ["games-b"]


async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok" and body["articles"] == 9
    assert body["status"] == "degraded"  # nothing fetched successfully yet


async def test_unknown_endpoint_uses_error_envelope(client):
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ------------------------------------------------------------- admin / initData
def _init_data(user_id: int, token: str = "123456:TEST-TOKEN", age: int = 0) -> str:
    return sign_init_data(
        {"auth_date": str(int(time.time()) - age), "query_id": "AAE", "user": json.dumps({"id": user_id, "first_name": "T"})},
        token,
    )


async def test_admin_requires_valid_signed_init_data(client):
    url = "/api/v1/admin/sources/world-a/refresh"
    assert (await client.post(url)).status_code == 401
    forged = _init_data(42, token="999:OTHER")
    assert (await client.post(url, headers={"Authorization": f"tma {forged}"})).status_code == 401
    expired = _init_data(42, age=3 * 86400)
    assert (await client.post(url, headers={"Authorization": f"tma {expired}"})).status_code == 401
    not_admin = _init_data(7)
    r = await client.post(url, headers={"Authorization": f"tma {not_admin}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = await client.post("/api/v1/admin/sources/missing/refresh", headers={"Authorization": f"tma {_init_data(42)}"})
    assert r.status_code == 404  # authorized, but no such source
