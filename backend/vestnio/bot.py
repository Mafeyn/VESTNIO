"""Telegram bot (aiogram 3): /start with a Mini App launch button + bot menu button.

    python -m vestnio.bot

Needs VESTNIO_BOT_TOKEN and VESTNIO_WEBAPP_URL (public HTTPS URL of the Mini App).
The token is read only here and in the API (initData validation); it never reaches
the browser bundle.

"Main Mini App" (the Open button in the bot profile and t.me/<bot>?startapp links)
is enabled in @BotFather: Bot Settings → Configure Mini App → set the same URL.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from .bot_replies import PAYLOAD, TEXT, lang_for, webapp_url
from .config import Settings, get_settings

log = logging.getLogger("vestnio.bot")
router = Router(name="vestnio")

_PAYLOAD = PAYLOAD


def _lang(message: Message) -> str:
    return lang_for(message.from_user.language_code if message.from_user else None)


def launch_keyboard(url: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]])


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, settings: Settings) -> None:
    t = TEXT[_lang(message)]
    payload = command.args if command.args and _PAYLOAD.match(command.args) else None
    url = webapp_url(settings.webapp_url or "", payload)
    label = t["open_article"] if payload else t["open"]
    await message.answer(t["start"], reply_markup=launch_keyboard(url, label))


@router.message(Command("help"))
async def on_help(message: Message, settings: Settings) -> None:
    t = TEXT[_lang(message)]
    await message.answer(t["help"], reply_markup=launch_keyboard(settings.webapp_url or "", t["open"]))


@router.message(F.text)
async def on_text(message: Message, settings: Settings) -> None:
    # Any other text: just offer the app (no chat features by design).
    t = TEXT[_lang(message)]
    await message.answer(t["help"], reply_markup=launch_keyboard(settings.webapp_url or "", t["open"]))


async def configure_bot(bot: Bot, settings: Settings) -> None:
    """Menu button, commands and descriptions (default = English, plus Russian)."""
    url = settings.webapp_url or ""
    # one global label (Telegram has no per-language menu button); the Russian edition uses "Новости"
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=TEXT["ru"]["menu"], web_app=WebAppInfo(url=url)))
    for lang in ("en", "ru"):
        t = TEXT[lang]
        code = None if lang == "en" else lang
        await bot.set_my_commands(
            [BotCommand(command="start", description=t["start_cmd"]), BotCommand(command="help", description=t["help_cmd"])],
            language_code=code,
        )
        await bot.set_my_short_description(short_description=t["short"], language_code=code)
    log.info("bot configured: menu button -> %s", url)


def _check(settings: Settings) -> tuple[str, str]:
    if not settings.bot_token:
        raise SystemExit("VESTNIO_BOT_TOKEN is not set (get one from @BotFather)")
    url = settings.webapp_url or ""
    if not url.startswith("https://"):
        raise SystemExit("VESTNIO_WEBAPP_URL must be a public https:// URL — Telegram only opens Mini Apps over HTTPS")
    return settings.bot_token.get_secret_value(), url


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    token, _ = _check(settings)
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(settings=settings)
    dp.include_router(router)
    try:
        hook = await bot.get_webhook_info()
        if hook.url and "--force" not in sys.argv:
            raise SystemExit(
                f"The bot is in webhook mode ({hook.url}), served by the hosted API.\n"
                "Polling would remove that webhook. Use --force to switch to local polling anyway."
            )
        await configure_bot(bot, settings)
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
        log.info("polling as @%s", me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
