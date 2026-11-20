"""Adding Telegram channels through the bot (admin flow)."""

import pytest
import respx
from pydantic import SecretStr

from vestnio.bot_admin import BotAdmin, check_channel, extract_channel
from vestnio.config import Settings
from vestnio.db import repository as repo
from vestnio.domain import SourceConfig
from vestnio.fetcher import Fetcher

from .conftest import requires_db

ADMIN, STRANGER = 111, 222

PREVIEW = """<html><body><div class="tgme_channel_info">
<div class="tgme_channel_info_header_title"><span>Новости Тест</span></div></div>
<div class="tgme_widget_message" data-post="newsy/5"><div class="tgme_widget_message_text">Первая новость дня в канале<br/>Подробности поста</div>
<a class="tgme_widget_message_date"><time datetime="2026-11-20T10:00:00+00:00"></time></a></div>
</body></html>"""


def _msg(text=None, user=ADMIN, **extra):
    return {"update_id": 1, "message": {"message_id": 9, "chat": {"id": user, "type": "private"}, "from": {"id": user}, "text": text, **extra}}


def _cb(data, user=ADMIN):
    return {"update_id": 2, "callback_query": {"id": "cq1", "from": {"id": user}, "data": data, "message": {"message_id": 9, "chat": {"id": user}}}}


@pytest.mark.parametrize(
    "message, expected",
    [
        ({"text": "https://t.me/newsy"}, "newsy"),
        ({"text": "глянь t.me/s/newsy пожалуйста"}, "newsy"),
        ({"text": "@newsy"}, "newsy"),
        ({"text": "t.me/joinchat/abc"}, None),
        ({"text": "@somebot"}, None),  # bots aren't channels
        ({"forward_origin": {"type": "channel", "chat": {"username": "fwdchan"}}, "text": "post"}, "fwdchan"),
        ({"text": "просто текст"}, None),
    ],
)
def test_extract_channel(message, expected):
    assert extract_channel(message) == expected


def _mock_tme():
    respx.get("https://t.me/robots.txt").respond(404)
    respx.get("https://t.me/s/newsy").respond(200, html=PREVIEW)
    respx.get("https://t.me/s/ghost").respond(302, headers={"Location": "https://t.me/ghost"})
    respx.get("https://t.me/ghost").respond(200, html="<html></html>")


@respx.mock
async def test_check_channel_exists_and_missing(settings):
    _mock_tme()
    async with Fetcher(settings) as f:
        ok = await check_channel(f, "newsy")
        missing = await check_channel(f, "ghost")
    assert ok.exists and ok.title == "Новости Тест" and ok.posts == 1
    assert not missing.exists and "приватный" in missing.reason


@pytest.fixture
def admin_settings(settings):
    settings.admin_ids = [ADMIN]
    settings.bot_token = SecretStr("1:T")
    return settings


@requires_db
@respx.mock
async def test_full_add_flow(admin_settings, sessionmaker):
    _mock_tme()
    async with Fetcher(admin_settings) as f:
        bot = BotAdmin(admin_settings, sessionmaker, f)

        # 1) link → existence check passes → category buttons
        [(method, payload)] = await bot.handle(_msg("https://t.me/newsy"))
        assert method == "sendMessage" and "Новости Тест" in payload["text"]
        buttons = [b["callback_data"] for b in payload["reply_markup"]["inline_keyboard"][0]]
        assert buttons == ["add:newsy:w", "add:newsy:t", "add:newsy:g"]

        # 2) pick "Технологии" → source created and polled right away
        calls = await bot.handle(_cb("add:newsy:t"))
        assert calls[0][0] == "answerCallbackQuery"
        assert "добавлен" in calls[1][1]["text"] and "Собрано постов: 1" in calls[1][1]["text"]

        # 3) same channel again → "already in VESTNIO", no buttons
        [(_, again)] = await bot.handle(_msg("@newsy"))
        assert "уже есть" in again["text"] and "reply_markup" not in again

        # 4) listed, then removed
        [(_, listing)] = await bot.handle(_msg("/channels"))
        assert "Новости Тест" in listing["text"]
        [(_, removed)] = await bot.handle(_msg("/remove @newsy"))
        assert "удалён" in removed["text"]

    async with sessionmaker() as s:
        src = await repo.get_source(s, "tg-newsy")
        assert src.origin == "bot" and src.category == "technology" and not src.enabled and src.added_by == ADMIN


REGISTRY_CH = SourceConfig(id="tg-reg", name="Registry Chan", url="https://t.me/s/RegChan", category="world", method="telegram")


@requires_db
@respx.mock
async def test_remove_registry_channel_via_buttons_and_bring_back(admin_settings, sessionmaker):
    respx.get("https://t.me/robots.txt").respond(404)
    respx.get("https://t.me/s/regchan").respond(200, html=PREVIEW.replace("Новости Тест", "Registry Chan"))
    respx.get("https://t.me/s/RegChan").respond(200, html=PREVIEW.replace("Новости Тест", "Registry Chan"))
    async with sessionmaker() as s:
        await repo.sync_sources(s, [REGISTRY_CH], 15)
    async with Fetcher(admin_settings) as f:
        bot = BotAdmin(admin_settings, sessionmaker, f)

        # /channels lists registry channels too, one 🗑 button each
        [(_, listing)] = await bot.handle(_msg("/channels"))
        assert "Registry Chan" in listing["text"]
        assert listing["reply_markup"]["inline_keyboard"] == [[{"text": "🗑 Registry Chan", "callback_data": "rm:RegChan"}]]

        # tap → confirmation (nothing removed yet)
        [_, (_, confirm)] = await bot.handle(_cb("rm:RegChan"))
        assert "Удалить канал" in confirm["text"]
        async with sessionmaker() as s:
            assert (await repo.get_source(s, "tg-reg")).enabled

        # "Нет" → back to the list, still enabled
        [_, (_, back)] = await bot.handle(_cb("rmn"))
        assert "Registry Chan" in back["text"]

        # "Да" → removed, only this channel
        [_, (_, done)] = await bot.handle(_cb("rmy:RegChan"))
        assert "удалён" in done["text"]

    async with sessionmaker() as s:
        await repo.sync_sources(s, [REGISTRY_CH], 15)  # sources.yaml still says enabled
        src = await repo.get_source(s, "tg-reg")
        assert not src.enabled and src.admin_disabled  # stays removed

    # sending the link again brings it back (same source, new category)
    async with Fetcher(admin_settings) as f:
        bot = BotAdmin(admin_settings, sessionmaker, f)
        [(_, offer)] = await bot.handle(_msg("t.me/RegChan"))
        assert "reply_markup" in offer  # not "already exists": it was removed
        await bot.handle(_cb("add:RegChan:g"))
    async with sessionmaker() as s:
        src = await repo.get_source(s, "tg-reg")
        assert src.enabled and not src.admin_disabled and src.category == "gaming"
        await repo.sync_sources(s, [REGISTRY_CH], 15)
        assert (await repo.get_source(s, "tg-reg")).enabled


@requires_db
async def test_remove_unknown_channel(admin_settings, sessionmaker):
    async with Fetcher(admin_settings) as f:
        [(_, p)] = await BotAdmin(admin_settings, sessionmaker, f).handle(_msg("/remove nosuchchan"))
    assert "нет в VESTNIO" in p["text"]


@requires_db
@respx.mock
async def test_missing_channel_is_reported(admin_settings, sessionmaker):
    _mock_tme()
    async with Fetcher(admin_settings) as f:
        [(_, payload)] = await BotAdmin(admin_settings, sessionmaker, f).handle(_msg("@ghost"))
    assert payload["text"].startswith("❌") and "reply_markup" not in payload


@requires_db
@respx.mock
async def test_registry_channel_counts_as_existing(admin_settings, sessionmaker):
    async with sessionmaker() as s:
        await repo.sync_sources(
            s, [SourceConfig(id="tg-newsy-reg", name="Newsy", url="https://t.me/s/Newsy", category="world", method="telegram")], 15
        )
    async with Fetcher(admin_settings) as f:
        [(_, payload)] = await BotAdmin(admin_settings, sessionmaker, f).handle(_msg("t.me/newsy"))
    assert "уже есть" in payload["text"]


@requires_db
async def test_bot_channels_survive_registry_sync(admin_settings, sessionmaker):
    async with sessionmaker() as s:
        await repo.add_bot_channel(s, username="keepme", title="Keep", category="world", added_by=ADMIN, default_poll=15)
        await repo.sync_sources(s, [], 15)  # registry file without that channel
        src = await repo.get_source(s, "tg-keepme")
    assert src.enabled and src.in_registry


@requires_db
async def test_non_admin_cannot_add(admin_settings, sessionmaker):
    async with Fetcher(admin_settings) as f:
        bot = BotAdmin(admin_settings, sessionmaker, f)
        assert await bot.handle(_msg("https://t.me/newsy", user=STRANGER)) is None  # normal help reply instead
        [(m, p)] = await bot.handle(_cb("add:newsy:w", user=STRANGER))
        assert m == "answerCallbackQuery" and p["show_alert"]
        [(_, myid)] = await bot.handle(_msg("/myid", user=STRANGER))
        assert str(STRANGER) in myid["text"]
