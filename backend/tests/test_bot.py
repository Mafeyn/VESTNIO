from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from vestnio.bot import _check, on_start, webapp_url
from vestnio.config import Settings


def test_webapp_url_adds_start_param():
    assert webapp_url("https://app.example.com/") == "https://app.example.com/"
    assert webapp_url("https://app.example.com/?v=2", "article_5") == "https://app.example.com/?v=2&tgWebAppStartParam=article_5"


def test_requires_token_and_https():
    with pytest.raises(SystemExit):
        _check(Settings(bot_token=None, webapp_url="https://x.example"))
    with pytest.raises(SystemExit, match="https"):
        _check(Settings(bot_token=SecretStr("1:A"), webapp_url="http://localhost:5173"))
    assert _check(Settings(bot_token=SecretStr("1:A"), webapp_url="https://x.example"))[1] == "https://x.example"


def _message(lang="ru"):
    return SimpleNamespace(from_user=SimpleNamespace(language_code=lang), answer=AsyncMock())


async def test_start_sends_launch_button():
    msg = _message("ru")
    await on_start(msg, SimpleNamespace(args=None), Settings(webapp_url="https://app.example.com/"))
    text = msg.answer.call_args.args[0]
    button = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert "VESTNIO" in text and button.web_app.url == "https://app.example.com/"
    assert button.text == "Открыть VESTNIO"


async def test_start_deep_link_is_validated():
    msg = _message("en")
    await on_start(msg, SimpleNamespace(args="article_42"), Settings(webapp_url="https://app.example.com/"))
    assert msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].web_app.url.endswith("tgWebAppStartParam=article_42")
    msg = _message("en")
    await on_start(msg, SimpleNamespace(args="<script>"), Settings(webapp_url="https://app.example.com/"))
    assert msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].web_app.url == "https://app.example.com/"
