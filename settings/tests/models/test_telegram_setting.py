from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from settings.models import TelegramSetting

pytestmark = pytest.mark.django_db


@patch("telegram_bot.utils.call_telegram_api")
def test_set_webhook_sends_url_and_secret(mock_call):
    mock_call.return_value.json.return_value = {"ok": True}
    setting = TelegramSetting.get_solo()
    setting.bot_token = "123:abc"  # noqa: S105
    setting.webhook_secret = "secret"  # noqa: S105

    result = setting.set_webhook("https://example.com/telegram/webhook/")

    assert result == {"ok": True}
    mock_call.assert_called_once_with(
        "setWebhook",
        {
            "url": "https://example.com/telegram/webhook/",
            "allowed_updates": ["message"],
            "secret_token": "secret",
        },
        bot_token="123:abc",  # noqa: S106
    )


@patch("telegram_bot.utils.call_telegram_api")
def test_set_webhook_without_secret_omits_it(mock_call):
    mock_call.return_value.json.return_value = {"ok": True}
    setting = TelegramSetting(bot_token="123:abc")  # noqa: S106

    setting.set_webhook("https://example.com/telegram/webhook/")

    assert "secret_token" not in mock_call.call_args.args[1]


def test_set_webhook_requires_token():
    with pytest.raises(ImproperlyConfigured):
        TelegramSetting(bot_token="").set_webhook("https://example.com/")
