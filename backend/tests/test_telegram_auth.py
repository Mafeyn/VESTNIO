import json
import time

import pytest

from vestnio.telegram_auth import InitDataError, sign_init_data, validate_init_data

TOKEN = "123456:ABC-DEF"


def _fields(**over):
    base = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": 279058397, "first_name": "Vlad", "username": "vlad", "language_code": "ru"}),
    }
    return {**base, **over}


def test_valid_init_data():
    data = validate_init_data(sign_init_data(_fields(), TOKEN), TOKEN)
    assert data.user.id == 279058397 and data.user.language_code == "ru"


def test_signature_field_is_ignored_in_hmac():
    raw = sign_init_data(_fields(), TOKEN) + "&signature=abc"
    assert validate_init_data(raw, TOKEN).user.id == 279058397


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("Vlad", "Evil"),  # tampered user
        lambda s: s + "&extra=1",  # injected field
        lambda s: s.split("&hash=")[0],  # hash removed
        lambda s: "",
    ],
)
def test_tampered_init_data_rejected(mutate):
    with pytest.raises(InitDataError):
        validate_init_data(mutate(sign_init_data(_fields(), TOKEN)), TOKEN)


def test_wrong_token_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(sign_init_data(_fields(), TOKEN), "654321:OTHER")


def test_expired_init_data_rejected():
    old = sign_init_data(_fields(auth_date=str(int(time.time()) - 2 * 86400)), TOKEN)
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(old, TOKEN, max_age_seconds=86400)
    assert validate_init_data(old, TOKEN, max_age_seconds=None)
