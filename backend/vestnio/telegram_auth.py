"""Server-side validation of Telegram Mini App `initData`.

The client sends the raw `Telegram.WebApp.initData` string (never `initDataUnsafe`)
in `Authorization: tma <initData>`. We verify its HMAC signature with the bot token,
following https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))

where data_check_string is every field except `hash` (and `signature`), sorted by key,
formatted "key=value" and joined with "\\n".
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    username: str | None = None
    language_code: str | None = None


@dataclass(slots=True, frozen=True)
class InitData:
    user: TelegramUser | None
    auth_date: int
    query_id: str | None
    raw: dict[str, str]


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a signed initData string (used by tests and local tooling)."""
    from urllib.parse import urlencode

    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    digest = hmac.new(_secret_key(bot_token), dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int | None = 86400) -> InitData:
    if not init_data:
        raise InitDataError("empty initData")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed initData") from exc
    fields = dict(pairs)
    received = fields.pop("hash", None)
    if not received:
        raise InitDataError("initData has no hash")
    fields.pop("signature", None)  # Ed25519 third-party signature, not part of the HMAC check

    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    expected = hmac.new(_secret_key(bot_token), dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("invalid initData signature")

    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError as exc:
        raise InitDataError("initData has no valid auth_date") from exc
    if max_age_seconds is not None and time.time() - auth_date > max_age_seconds:
        raise InitDataError("initData expired")

    user = None
    if "user" in fields:
        try:
            u = json.loads(fields["user"])
            user = TelegramUser(
                id=int(u["id"]),
                first_name=u.get("first_name"),
                username=u.get("username"),
                language_code=u.get("language_code"),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InitDataError("initData user is malformed") from exc
    return InitData(user=user, auth_date=auth_date, query_id=fields.get("query_id"), raw=fields)
