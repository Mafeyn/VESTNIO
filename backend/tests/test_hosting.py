"""Serverless hosting pieces: database URL handling and the Telegram webhook."""

import httpx
import pytest
import respx
from pydantic import SecretStr

from vestnio.api.app import create_app
from vestnio.bot_replies import build_reply
from vestnio.config import Settings, normalize_database_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?ssl=require",
        ),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ('﻿"postgresql://u:p@h/db?sslmode=require"\r\n', "postgresql+asyncpg://u:p@h/db?ssl=require"),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_plain_database_url_env_is_accepted(monkeypatch):
    monkeypatch.delenv("VESTNIO_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@neon.example/db?sslmode=require")
    assert Settings(_env_file=None).database_url == "postgresql+asyncpg://u:p@neon.example/db?ssl=require"


def _update(text, chat_type="private", lang="ru"):
    return {"update_id": 1, "message": {"message_id": 5, "text": text, "chat": {"id": 42, "type": chat_type}, "from": {"id": 42, "language_code": lang}}}


def test_build_reply():
    r = build_reply(_update("/start"), "https://app.example/")
    assert r["chat_id"] == 42 and "VESTNIO" in r["text"]
    assert r["reply_markup"]["inline_keyboard"][0][0] == {"text": "Открыть VESTNIO", "web_app": {"url": "https://app.example/"}}
    deep = build_reply(_update("/start article_7", lang="en"), "https://app.example/")
    assert deep["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://app.example/?tgWebAppStartParam=article_7"
    assert build_reply(_update("/start <script>"), "https://app.example/")["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://app.example/"
    assert build_reply(_update("hello", chat_type="group"), "https://app.example/") is None  # groups ignored
    assert build_reply({"update_id": 2, "edited_message": {}}, "https://app.example/") is None


def _client(**over):
    s = Settings(
        _env_file=None,
        bot_token=SecretStr("123:ABC"),
        webhook_secret=SecretStr("s3cret"),
        webapp_url="https://app.example/",
        **over,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(s)), base_url="http://test")


@respx.mock
async def test_webhook_replies_with_launch_button():
    sent = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(json={"ok": True})
    async with _client() as c:
        r = await c.post("/api/telegram/webhook", json=_update("/start"), headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert r.status_code == 200 and sent.call_count == 1
    assert b'"web_app"' in sent.calls.last.request.content


@respx.mock
async def test_webhook_rejects_wrong_secret_and_survives_errors():
    sent = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(500)
    async with _client() as c:
        bad = await c.post("/api/telegram/webhook", json=_update("/start"), headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
        ok = await c.post("/api/telegram/webhook", json=_update("/start"), headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert bad.status_code == 403 and ok.status_code == 200  # Telegram error doesn't cause redelivery
    assert sent.call_count == 1


async def test_webhook_disabled_without_secret():
    s = Settings(_env_file=None, bot_token=SecretStr("123:ABC"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(s)), base_url="http://test") as c:
        r = await c.post("/api/telegram/webhook", json={})
    assert r.status_code == 404
