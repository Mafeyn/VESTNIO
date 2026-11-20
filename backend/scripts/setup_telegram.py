"""Point the bot at a hosted VESTNIO (webhook mode) and set its menu button and commands.

    python scripts/setup_telegram.py https://vestnio.vercel.app

Reads from backend/.env (or the environment):
  VESTNIO_BOT_TOKEN       bot token from @BotFather
  VESTNIO_WEBHOOK_SECRET  random string; the same value must be set on the hosting
After this the long-polling bot (python -m vestnio.bot) must NOT be started: it
would delete the webhook. Run with --polling to switch back to local polling.
"""

from __future__ import annotations

import sys

import httpx

from vestnio.bot_replies import TEXT
from vestnio.config import get_settings


def call(token: str, method: str, **payload) -> dict:
    r = httpx.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=20)
    data = r.json()
    if not data.get("ok"):
        raise SystemExit(f"{method} failed: {data.get('description')}")
    return data


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    s = get_settings()
    if not s.bot_token:
        raise SystemExit("VESTNIO_BOT_TOKEN is not set")
    token = s.bot_token.get_secret_value()

    if "--polling" in sys.argv:
        call(token, "deleteWebhook", drop_pending_updates=False)
        print("webhook removed; start the local bot with: python -m vestnio.bot")
        return

    if not args or not args[0].startswith("https://"):
        raise SystemExit("usage: python scripts/setup_telegram.py https://<your-app>.vercel.app")
    base = args[0].rstrip("/") + "/"
    if not s.webhook_secret:
        raise SystemExit("VESTNIO_WEBHOOK_SECRET is not set (any long random string, same as on the hosting)")

    call(
        token,
        "setWebhook",
        url=base + "api/telegram/webhook",
        secret_token=s.webhook_secret.get_secret_value(),
        allowed_updates=["message"],
        drop_pending_updates=True,
    )
    call(token, "setChatMenuButton", menu_button={"type": "web_app", "text": TEXT["ru"]["menu"], "web_app": {"url": base}})
    for lang in ("en", "ru"):
        t = TEXT[lang]
        extra = {} if lang == "en" else {"language_code": lang}
        call(
            token,
            "setMyCommands",
            commands=[{"command": "start", "description": t["start_cmd"]}, {"command": "help", "description": t["help_cmd"]}],
            **extra,
        )
        call(token, "setMyShortDescription", short_description=t["short"], **extra)
    info = call(token, "getWebhookInfo")["result"]
    me = call(token, "getMe")["result"]
    print(f"@{me['username']}: webhook -> {info['url']} (pending updates: {info.get('pending_update_count', 0)})")
    print(f"menu button -> {base}")
    print("Also set this URL in @BotFather → Bot Settings → Configure Mini App.")


if __name__ == "__main__":
    main()
