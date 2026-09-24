from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from celery.exceptions import Retry

from telegram_bot.tasks import reply_to_message
from telegram_bot.tests.factories import TelegramUserFactory
from telegram_bot.tests.test_utils import fake_response

pytestmark = pytest.mark.django_db


@pytest.fixture
def telegram_user():
    return TelegramUserFactory.create(telegram_id=555)


@patch("telegram_bot.models.TelegramUser.send_chat_action")
@patch("telegram_bot.models.TelegramUser.send_message")
def test_sends_typing_then_reply(mock_send, mock_action, telegram_user):
    mock_send.return_value = fake_response()

    reply_to_message.apply(args=(telegram_user.pk, 42, "hi")).get()

    mock_action.assert_called_once_with("typing")
    mock_send.assert_called_once_with("hi", reply_to_message_id=42)


@patch("telegram_bot.models.TelegramUser.send_chat_action")
@patch("telegram_bot.models.TelegramUser.send_message")
def test_chat_action_failure_does_not_block_reply(
    mock_send,
    mock_action,
    telegram_user,
):
    mock_action.side_effect = requests.ConnectionError("down")
    mock_send.return_value = fake_response()

    reply_to_message.apply(args=(telegram_user.pk, 42, "hi")).get()

    mock_send.assert_called_once()


@patch("telegram_bot.models.TelegramUser.send_message")
def test_missing_user_is_skipped(mock_send):
    reply_to_message.apply(args=(999_999, 42, "hi")).get()

    mock_send.assert_not_called()


@patch("telegram_bot.models.TelegramUser.send_chat_action", new=MagicMock())
@patch("telegram_bot.models.TelegramUser.send_message")
@patch("telegram_bot.tasks.reply_to_message.retry", side_effect=Retry)
class TestRetries:
    def test_network_error_retries(self, mock_retry, mock_send, telegram_user):
        mock_send.side_effect = requests.ConnectionError("down")

        with pytest.raises(Retry):
            reply_to_message(telegram_user.pk, 42, "hi")

        assert isinstance(mock_retry.call_args.kwargs["exc"], requests.ConnectionError)

    def test_429_retries_after_retry_after(self, mock_retry, mock_send, telegram_user):
        mock_send.return_value = fake_response(
            429,
            {"ok": False, "parameters": {"retry_after": 17}},
        )

        with pytest.raises(Retry):
            reply_to_message(telegram_user.pk, 42, "hi")

        mock_retry.assert_called_once_with(countdown=17)

    def test_5xx_retries(self, mock_retry, mock_send, telegram_user):
        mock_send.return_value = fake_response(502, {"ok": False})

        with pytest.raises(Retry):
            reply_to_message(telegram_user.pk, 42, "hi")

        mock_retry.assert_called_once_with()

    @pytest.mark.parametrize("status_code", [400, 403])
    def test_4xx_does_not_retry(
        self,
        mock_retry,
        mock_send,
        telegram_user,
        status_code,
    ):
        mock_send.return_value = fake_response(status_code, {"ok": False})

        reply_to_message(telegram_user.pk, 42, "hi")

        mock_retry.assert_not_called()


@patch("config.celery_app.app.amqp.send_task_message")
def test_reply_is_published_ahead_of_other_tasks(mock_send_task_message):
    from instagram.tasks.story import moderate_story_content  # noqa: PLC0415

    reply_to_message.delay(1, 2, "hi")
    moderate_story_content.delay("story-id")

    priorities = [c.kwargs["priority"] for c in mock_send_task_message.call_args_list]
    assert priorities == [0, 5]
