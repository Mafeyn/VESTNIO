"""Admin flow of the bot: add public Telegram channels as news sources.

  • send the bot a t.me link, an @username, or forward a post from the channel
  • the bot checks that the channel exists and is public (has a t.me/s/ preview)
    and that it isn't already in VESTNIO
  • pick a category with the buttons → the channel is saved and polled at once
  • /channels lists every Telegram channel with a 🗑 button (asks to confirm);
    /remove @channel removes one directly. Removed registry channels stay off
    across sources.yaml syncs; sending the link again brings a channel back
  • /myid shows your Telegram user id (put it in VESTNIO_ADMIN_IDS)

Only users listed in VESTNIO_ADMIN_IDS can manage channels; for everyone else the
bot behaves as before. Handlers return Bot API calls as (method, payload) pairs.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .db import repository as repo
from .fetcher import FetchError, Fetcher

log = logging.getLogger("vestnio.bot_admin")

Call = tuple[str, dict[str, Any]]

CATEGORIES = {"world": "🌍 Мир", "technology": "💻 Технологии", "gaming": "🎮 Игры"}
_CAT_CODE = {"w": "world", "t": "technology", "g": "gaming"}
_USERNAME = r"[A-Za-z][A-Za-z0-9_]{3,31}"
_LINK = re.compile(rf"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?({_USERNAME})\b", re.I)
_AT = re.compile(rf"(?:^|\s)@({_USERNAME})\b")
_RESERVED = {"joinchat", "addstickers", "share", "proxy", "socks", "iv", "c", "s"}


@dataclass(slots=True)
class ChannelCheck:
    username: str
    exists: bool
    title: str = ""
    posts: int = 0
    reason: str = ""


def extract_channel(message: dict[str, Any]) -> str | None:
    """@username of the channel a message refers to: forwarded post, t.me link or @mention."""
    origin = message.get("forward_origin") or {}
    chat = origin.get("chat") if origin.get("type") == "channel" else message.get("forward_from_chat")
    if chat and chat.get("username"):
        return chat["username"]
    text = message.get("text") or message.get("caption") or ""
    for rx in (_LINK, _AT):
        m = rx.search(text)
        if m and m.group(1).lower() not in _RESERVED and not m.group(1).lower().endswith("bot"):
            return m.group(1)
    return None


async def check_channel(fetcher: Fetcher, username: str) -> ChannelCheck:
    """Does the channel exist and is it public? Uses Telegram's own web preview."""
    try:
        res = await fetcher.get(f"https://t.me/s/{username}", retries=1, timeout=10)
    except FetchError as exc:
        return ChannelCheck(username, False, reason=f"Telegram не ответил ({exc.__class__.__name__})")
    if "/s/" not in res.url:
        # t.me redirects to the plain page when there is no public preview
        return ChannelCheck(username, False, reason="канал не найден, приватный или у него закрыто превью")
    soup = BeautifulSoup(res.text, "html.parser")
    title_el = soup.select_one(".tgme_channel_info_header_title")
    if not title_el:
        return ChannelCheck(username, False, reason="по этому адресу нет публичного канала")
    posts = len(soup.select(".tgme_widget_message[data-post]"))
    return ChannelCheck(username, True, title=title_el.get_text(" ", strip=True), posts=posts)


def _send(chat_id: int, text: str, markup: dict | None = None) -> Call:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    return ("sendMessage", payload)


def _category_buttons(username: str) -> dict:
    row = [{"text": label, "callback_data": f"add:{username}:{cat[0]}"} for cat, label in CATEGORIES.items()]
    return {"inline_keyboard": [row, [{"text": "✖️ Отмена", "callback_data": "add:-:x"}]]}


class BotAdmin:
    def __init__(self, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], fetcher: Fetcher):
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.fetcher = fetcher

    def is_admin(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id in self.settings.admin_ids

    async def handle(self, update: dict[str, Any]) -> list[Call] | None:
        """Bot API calls for admin-related updates, or None to fall back to the normal reply."""
        if "callback_query" in update:
            return await self._on_callback(update["callback_query"])
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return None
        user_id = (message.get("from") or {}).get("id")
        text = (message.get("text") or "").strip()
        command = text.split(" ")[0].split("@")[0].lower() if text.startswith("/") else ""

        if command == "/myid":
            note = "" if self.is_admin(user_id) else "\n\nЧтобы добавлять каналы, этот ID нужно указать в VESTNIO_ADMIN_IDS."
            return [_send(chat["id"], f"Ваш Telegram ID: <code>{user_id}</code>{note}")]
        if not self.is_admin(user_id):
            return None  # regular users: normal /start and help replies
        if command == "/channels":
            return [await self._list(chat["id"])]
        if command == "/remove":
            return [await self._remove(chat["id"], text)]
        if command in ("/start", "/help"):
            return None
        username = extract_channel(message)
        if username:
            return [await self._propose(chat["id"], username)]
        if command == "/add":
            return [_send(chat["id"], "Пришлите ссылку на канал (<code>t.me/канал</code>), <code>@канал</code> или перешлите пост из него.")]
        return None

    async def _propose(self, chat_id: int, username: str) -> Call:
        # 1) already in VESTNIO?
        async with self.sessionmaker() as s:
            existing = await repo.find_channel_source(s, username)
        if existing is not None:
            cat = CATEGORIES.get(existing.category, existing.category)
            return _send(chat_id, f"ℹ️ Канал <b>{html.escape(existing.name)}</b> (@{username}) уже есть в VESTNIO — категория {cat}.")
        # 2) does it exist and is it public?
        check = await check_channel(self.fetcher, username)
        if not check.exists:
            return _send(chat_id, f"❌ @{html.escape(username)}: {check.reason}. Добавить можно только публичный канал.")
        posts = f"{check.posts} последних постов в превью" if check.posts else "постов в превью пока нет"
        return _send(
            chat_id,
            f"✅ Нашёл канал <b>{html.escape(check.title)}</b> (@{username}), {posts}.\nВ какую категорию добавить?",
            _category_buttons(username),
        )

    async def _on_callback(self, cq: dict[str, Any]) -> list[Call] | None:
        data = cq.get("data") or ""
        if not data.startswith(("add:", "rm:", "rmy:", "rmn")):
            return None
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        user_id = (cq.get("from") or {}).get("id")
        answer: Call = ("answerCallbackQuery", {"callback_query_id": cq.get("id")})
        if not self.is_admin(user_id):
            return [("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Только для администратора", "show_alert": True})]

        def edit(text: str, markup: dict | None = None) -> Call:
            payload = {"chat_id": chat_id, "message_id": msg.get("message_id"), "text": text, "parse_mode": "HTML"}
            if markup:
                payload["reply_markup"] = markup
            return ("editMessageText", payload)

        if data.startswith(("rm:", "rmy:", "rmn")):
            return [answer, await self._on_remove_button(data, edit)]

        _, username, code = (data.split(":") + ["", ""])[:3]
        if code == "x":
            return [answer, edit("Добавление отменено.")]
        category = _CAT_CODE.get(code)
        if not category or not re.fullmatch(_USERNAME, username):
            return [answer]
        check = await check_channel(self.fetcher, username)  # re-check: the button may be old
        if not check.exists:
            return [answer, edit(f"❌ @{html.escape(username)}: {check.reason}.")]
        async with self.sessionmaker() as s:
            src, created = await repo.add_bot_channel(
                s, username=username, title=check.title, category=category, added_by=user_id,
                default_poll=self.settings.default_poll_minutes,
            )
            source_id, name = src.id, src.name
        if not created:
            return [answer, edit(f"ℹ️ Канал <b>{html.escape(name)}</b> уже есть в VESTNIO.")]
        found = await self._poll_now(source_id)
        tail = f"Собрано постов: {found}." if found is not None else "Посты появятся при следующем сборе (до 15 минут)."
        return [answer, edit(f"✅ Канал <b>{html.escape(name)}</b> добавлен в {CATEGORIES[category]}.\n{tail}")]

    async def _poll_now(self, source_id: str) -> int | None:
        from .ingestion import IngestionService

        service = IngestionService(self.settings, self.sessionmaker, self.fetcher)
        try:
            result = await service.poll_source_id(source_id)
        except Exception:
            log.exception("first poll of %s failed", source_id)
            return None
        return result.inserted if result and result.ok else None

    async def _channels_view(self) -> tuple[str, dict | None]:
        """Text + one '🗑 name' button per channel (all Telegram channels in VESTNIO)."""
        async with self.sessionmaker() as s:
            rows = await repo.list_channels(s)
        if not rows:
            return "В VESTNIO пока нет Telegram-каналов. Пришлите ссылку на канал, чтобы добавить.", None
        lines, buttons, current = [], [], None
        for r in rows:
            if r.category != current:
                current = r.category
                lines.append(f"\n<b>{CATEGORIES.get(r.category, r.category)}</b>")
            username = repo.channel_username(r)
            lines.append(f"• {html.escape(r.name)} — @{username}")
            buttons.append([{"text": f"🗑 {r.name[:40]}", "callback_data": f"rm:{username}"[:64]}])
        text = f"Telegram-каналы в VESTNIO ({len(rows)}):\n" + "\n".join(lines) + "\n\nНажмите на канал ниже, чтобы удалить его."
        return text, {"inline_keyboard": buttons[:95]}

    async def _list(self, chat_id: int) -> Call:
        text, markup = await self._channels_view()
        return _send(chat_id, text, markup)

    async def _on_remove_button(self, data: str, edit) -> Call:
        kind, _, username = data.partition(":")
        if kind == "rmn" or not re.fullmatch(_USERNAME, username or ""):
            text, markup = await self._channels_view()  # "Нет" → back to the list
            return edit(text, markup)
        if kind == "rm":  # ask first: one accidental tap must not remove a channel
            async with self.sessionmaker() as s:
                src = await repo.find_channel_source(s, username)
            if src is None:
                text, markup = await self._channels_view()
                return edit("Этого канала уже нет в VESTNIO.\n\n" + text, markup)
            confirm = {"inline_keyboard": [[
                {"text": "🗑 Да, удалить", "callback_data": f"rmy:{username}"[:64]},
                {"text": "↩️ Нет", "callback_data": "rmn"},
            ]]}
            return edit(f"Удалить канал <b>{html.escape(src.name)}</b> (@{username}) из VESTNIO?\n"
                        "Его посты пропадут из ленты. Вернуть можно, прислав ссылку на канал снова.", confirm)
        async with self.sessionmaker() as s:  # rmy: confirmed
            src = await repo.disable_channel(s, username)
        if src is None:
            return edit("Этого канала уже нет в VESTNIO.")
        return edit(f"🗑 Канал <b>{html.escape(src.name)}</b> удалён из VESTNIO.\nВернуть: пришлите ссылку t.me/{username}")

    async def _remove(self, chat_id: int, text: str) -> Call:
        arg = text.partition(" ")[2].strip()
        username = extract_channel({"text": arg}) or (arg if re.fullmatch(_USERNAME, arg) else None)
        if not username:
            return _send(chat_id, "Укажите канал: <code>/remove @канал</code> — или выберите его в /channels")
        async with self.sessionmaker() as s:
            src = await repo.disable_channel(s, username)
        if src is None:
            return _send(chat_id, f"Канала @{html.escape(username)} нет в VESTNIO. Список каналов: /channels")
        return _send(chat_id, f"🗑 Канал <b>{html.escape(src.name)}</b> удалён из VESTNIO.\nВернуть: пришлите ссылку t.me/{username}")
