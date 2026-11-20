"""Upload assets/bot-avatar.png as the bot's profile photo (Bot API setMyProfilePhoto).

    python scripts/set_bot_avatar.py [path/to/image.png]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InputProfilePhotoStatic

from vestnio.config import get_settings

DEFAULT = Path(__file__).resolve().parent.parent / "assets" / "bot-avatar.png"


async def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    token = get_settings().bot_token
    if not token:
        raise SystemExit("VESTNIO_BOT_TOKEN is not set")
    bot = Bot(token.get_secret_value())
    try:
        ok = await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=FSInputFile(path)))
        me = await bot.get_me()
        print(f"profile photo set for @{me.username}: {ok}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
