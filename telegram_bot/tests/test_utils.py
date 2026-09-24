from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status

from api_logs.models import APIRequestLog
from core.users.tests.factories import UserFactory
from settings.models import TelegramSetting
from telegram_bot.models import TelegramUser
from telegram_bot.tests.factories import TelegramUserFactory
from telegram_bot.utils import TelegramUserConflict
from telegram_bot.utils import call_telegram_api
from telegram_bot.utils import parse_command
from telegram_bot.utils import upsert_telegram_user

pytestmark = pytest.mark.django_db

TOKEN = "123456:SECRET-TOKEN"  # noqa: S105
TELEGRAM_ID = 111


def telegram_user_data(**overrides):
    return {
        "id": TELEGRAM_ID,
        "is_bot": False,
        "first_name": "Budi",
        "last_name": "Santoso",
        "username": "budi",
        "language_code": "id",
        **overrides,
    }


@pytest.fixture
def bot_token():
    setting = TelegramSetting.get_solo()
    setting.bot_token = TOKEN
    setting.save()
    return TOKEN


def fake_response(status_code=200, json_data=None):
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400  # noqa: PLR2004
    response.headers = {}
    response.json.return_value = json_data if json_data is not None else {"ok": True}
    return response


class TestUpsertTelegramUser:
    def test_creates_user(self):
        telegram_user = upsert_telegram_user(telegram_user_data())

        assert telegram_user.telegram_id == TELEGRAM_ID
        assert telegram_user.username == "budi"
        assert telegram_user.language_code == "id"
        assert telegram_user.user.name == "Budi Santoso"

    def test_missing_optional_fields_use_defaults(self):
        telegram_user = upsert_telegram_user({"id": 222, "first_name": "Ani"})

        assert telegram_user.username == ""
        assert telegram_user.last_name == ""
        assert telegram_user.is_premium is False

    def test_empty_first_name_falls_back_to_id(self):
        telegram_user = upsert_telegram_user({"id": 333, "first_name": ""})

        assert telegram_user.first_name == "333"

    def test_updates_changed_fields_and_django_user_name(self):
        TelegramUserFactory.create(telegram_id=111, first_name="Old", last_name="")

        telegram_user = upsert_telegram_user(
            telegram_user_data(first_name="New", username="new_name"),
        )

        telegram_user.refresh_from_db()
        assert telegram_user.first_name == "New"
        assert telegram_user.username == "new_name"
        assert telegram_user.user.name == "New Santoso"
        assert TelegramUser.objects.count() == 1

    def test_unchanged_user_adds_no_history(self):
        upsert_telegram_user(telegram_user_data())
        history_count = TelegramUser.history.count()

        upsert_telegram_user(telegram_user_data())

        assert TelegramUser.history.count() == history_count

    def test_taken_username_raises_conflict(self):
        UserFactory.create(username="telegram_111")

        with pytest.raises(TelegramUserConflict):
            upsert_telegram_user(telegram_user_data())

        assert not TelegramUser.objects.filter(telegram_id=111).exists()


class TestCallTelegramApi:
    def test_requires_token(self):
        with pytest.raises(ImproperlyConfigured):
            call_telegram_api("getMe", {})

    @patch("telegram_bot.utils.requests.post")
    def test_posts_and_logs_masked_url(self, mock_post, bot_token):
        mock_post.return_value = fake_response(json_data={"ok": True})

        response = call_telegram_api("sendMessage", {"chat_id": 1})

        assert response is mock_post.return_value
        mock_post.assert_called_once_with(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": 1},
            timeout=10,
        )
        log = APIRequestLog.objects.get()
        assert log.url == "https://api.telegram.org/bot***/sendMessage"
        assert log.status == APIRequestLog.STATUS_SUCCESS
        assert log.response_body == {"ok": True}

    @patch("telegram_bot.utils.requests.post")
    def test_error_response_is_returned_not_raised(self, mock_post, bot_token):
        mock_post.return_value = fake_response(403, {"ok": False})

        response = call_telegram_api("sendMessage", {"chat_id": 1})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert APIRequestLog.objects.get().status == APIRequestLog.STATUS_ERROR

    @patch("telegram_bot.utils.requests.post")
    def test_network_error_is_masked(self, mock_post, bot_token):
        mock_post.side_effect = requests.ConnectionError(
            f"Max retries exceeded with url: /bot{TOKEN}/sendMessage",
        )

        with pytest.raises(requests.ConnectionError) as exc_info:
            call_telegram_api("sendMessage", {"chat_id": 1})

        assert TOKEN not in str(exc_info.value)
        assert exc_info.value.__cause__ is None
        log = APIRequestLog.objects.get()
        assert TOKEN not in log.error_message
        assert log.status == APIRequestLog.STATUS_ERROR

    @patch("telegram_bot.utils.requests.post")
    def test_timeout_is_logged_as_timeout(self, mock_post, bot_token):
        mock_post.side_effect = requests.Timeout("timed out")

        with pytest.raises(requests.Timeout):
            call_telegram_api("sendMessage", {"chat_id": 1})

        assert APIRequestLog.objects.get().status == APIRequestLog.STATUS_TIMEOUT

    @patch("telegram_bot.utils.requests.post")
    def test_explicit_token_overrides_setting(self, mock_post, bot_token):
        mock_post.return_value = fake_response()

        call_telegram_api("getMe", {}, bot_token="other:token")  # noqa: S106

        assert (
            mock_post.call_args.args[0]
            == "https://api.telegram.org/botother:token/getMe"
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start", "start"),
        ("/start ref_123", "start"),
        ("/start@InstarchiverBot", "start"),
        ("/START", "start"),
        ("hello", None),
        ("/", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_command(text, expected):
    assert parse_command(text) == expected
