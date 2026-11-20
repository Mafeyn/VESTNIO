"""Bot texts and reply logic shared by the long-polling bot (vestnio.bot, aiogram)
and the webhook endpoint (/api/telegram/webhook) used on serverless hosting."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

TEXT = {
    "ru": {
        "start": (
            "<b>VESTNIO</b> — новости игр, мира и технологий в одной ленте.\n\n"
            "Свежие статьи из проверенных источников, поиск, фильтры и закладки. "
            "Каждая новость ведёт на оригинальную публикацию."
        ),
        "open": "Открыть VESTNIO",
        "open_article": "Открыть статью",
        "help": (
            "Нажмите <b>Открыть VESTNIO</b> или кнопку меню рядом с полем ввода.\n\n"
            "/start — открыть приложение\n/help — помощь"
        ),
        "menu": "Новости",
        "start_cmd": "Открыть приложение",
        "help_cmd": "Помощь",
        "short": "Новости игр, мира и технологий в одной ленте.",
    },
    "en": {
        "start": (
            "<b>VESTNIO</b> — gaming, world and tech news in one feed.\n\n"
            "Fresh stories from verified sources, with search, filters and bookmarks. "
            "Every story links to the original publication."
        ),
        "open": "Open VESTNIO",
        "open_article": "Open article",
        "help": "Tap <b>Open VESTNIO</b> or the menu button next to the message field.\n\n/start — open the app\n/help — help",
        "menu": "News",
        "start_cmd": "Open the app",
        "help_cmd": "Help",
        "short": "Gaming, world and tech news in one feed.",
    },
}

PAYLOAD = re.compile(r"^article_\d{1,18}$")


def lang_for(language_code: str | None) -> str:
    return "ru" if (language_code or "").startswith(("ru", "uk", "be", "kk")) else "en"


def webapp_url(base: str, start_param: str | None = None) -> str:
    """Mini App URL; a validated deep-link payload is passed as tgWebAppStartParam."""
    if not start_param:
        return base
    parts = urlsplit(base)
    query = "&".join(filter(None, [parts.query, urlencode({"tgWebAppStartParam": start_param})]))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def launch_markup(url: str, label: str) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]}


def build_reply(update: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    """Bot API sendMessage payload for an incoming update, or None to ignore it."""
    message = update.get("message") or {}
    text = message.get("text")
    chat = message.get("chat") or {}
    if not text or "id" not in chat or chat.get("type") != "private":
        return None  # only answer people in private chats
    t = TEXT[lang_for((message.get("from") or {}).get("language_code"))]
    command, _, args = text.strip().partition(" ")
    command = command.split("@")[0]
    if command == "/start":
        payload = args.strip() if PAYLOAD.match(args.strip()) else None
        body, url = t["start"], webapp_url(base_url, payload)
        label = t["open_article"] if payload else t["open"]
    else:  # /help and any other text: just offer the app (no chat features by design)
        body, url, label = t["help"], base_url, t["open"]
    return {
        "chat_id": chat["id"],
        "text": body,
        "parse_mode": "HTML",
        "reply_markup": launch_markup(url, label),
    }
