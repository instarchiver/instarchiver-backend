from itertools import count
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from settings.models import TelegramSetting
from telegram_bot.models import TelegramUser
from telegram_bot.tests.factories import TelegramUserFactory
from telegram_bot.views import FALLBACK_REPLY

SECRET = "webhook-secret_123"  # noqa: S105
URL = reverse("telegram_bot:webhook")
MESSAGE_ID = 42
update_ids = count(1)


def make_update(text="/start", **message_overrides):
    message: dict = {
        "message_id": MESSAGE_ID,
        "date": 1_700_000_000,
        "from": {
            "id": 111,
            "is_bot": False,
            "first_name": "Budi",
            "username": "budi",
        },
        "chat": {"id": 111, "type": "private"},
        **message_overrides,
    }
    if text is not None:
        message["text"] = text
    return {"update_id": next(update_ids), "message": message}


@patch("telegram_bot.views.reply_to_message.delay")
class TelegramWebhookViewTest(TestCase):
    def setUp(self):
        cache.clear()
        setting = TelegramSetting.get_solo()
        setting.webhook_secret = SECRET
        setting.save()
        self.client = APIClient()

    def post(self, data, secret=SECRET):
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(URL, data, format="json", headers=headers)

    def test_wrong_secret_is_forbidden(self, mock_delay):
        response = self.post(make_update(), secret="wrong")  # noqa: S106

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_delay.assert_not_called()

    def test_missing_secret_is_forbidden(self, mock_delay):
        response = self.post(make_update(), secret=None)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unconfigured_secret_is_forbidden(self, mock_delay):
        TelegramSetting.objects.update(webhook_secret="")

        response = self.post(make_update(), secret="")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_start_creates_user_and_queues_reply(self, mock_delay):
        response = self.post(make_update("/start"))

        assert response.status_code == status.HTTP_200_OK
        telegram_user = TelegramUser.objects.get(telegram_id=111)
        assert telegram_user.first_name == "Budi"
        telegram_user_pk, message_id, text = mock_delay.call_args.args
        assert telegram_user_pk == telegram_user.pk
        assert message_id == MESSAGE_ID
        assert "Budi" in text

    def test_start_variants_get_greeting(self, mock_delay):
        for text in ["/start", "/start ref_123", "/start@InstarchiverBot"]:
            with self.subTest(text=text):
                mock_delay.reset_mock()

                self.post(make_update(text))

                _, message_id, reply = mock_delay.call_args.args
                assert message_id == MESSAGE_ID
                assert reply == "Hi Budi! Welcome to Instarchiver."

    def test_unknown_messages_get_fallback(self, mock_delay):
        for text in ["hello", "/unknown", None]:
            with self.subTest(text=text):
                mock_delay.reset_mock()

                self.post(make_update(text))

                _, message_id, reply = mock_delay.call_args.args
                assert message_id == MESSAGE_ID
                assert reply == FALLBACK_REPLY

    def test_missing_message_id_is_rolled_back(self, mock_delay):
        update = make_update()
        del update["message"]["message_id"]

        response = self.post(update)

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()
        assert not TelegramUser.objects.exists()

    def test_queue_failure_still_returns_ok(self, mock_delay):
        mock_delay.side_effect = ConnectionError("broker down")

        response = self.post(make_update())

        assert response.status_code == status.HTTP_200_OK

    def test_existing_user_is_updated(self, mock_delay):
        TelegramUserFactory.create(telegram_id=111, username="old")

        self.post(make_update())

        assert TelegramUser.objects.get(telegram_id=111).username == "budi"
        assert TelegramUser.objects.count() == 1

    def test_duplicate_update_is_processed_once(self, mock_delay):
        update = make_update()

        self.post(update)
        self.post(update)

        assert mock_delay.call_count == 1

    def test_non_message_update_is_ignored(self, mock_delay):
        response = self.post({"update_id": next(update_ids), "edited_message": {}})

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()

    def test_group_message_is_ignored(self, mock_delay):
        self.post(make_update(chat={"id": -100, "type": "group"}))

        mock_delay.assert_not_called()
        assert not TelegramUser.objects.exists()

    def test_bot_sender_is_ignored(self, mock_delay):
        self.post(
            make_update(**{"from": {"id": 222, "is_bot": True, "first_name": "Bot"}}),
        )

        mock_delay.assert_not_called()

    def test_conflict_returns_ok_without_reply(self, mock_delay):
        UserFactory.create(username="telegram_111")

        response = self.post(make_update())

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()

    def test_malformed_payload_returns_ok(self, mock_delay):
        response = self.post({"update_id": next(update_ids), "message": {"text": "x"}})

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()


@pytest.mark.parametrize("method", ["get", "put"])
def test_only_post_is_allowed(method, db):
    response = getattr(APIClient(), method)(URL)

    assert response.status_code in {
        status.HTTP_403_FORBIDDEN,
        status.HTTP_405_METHOD_NOT_ALLOWED,
    }
