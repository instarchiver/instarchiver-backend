import logging
from http import HTTPStatus

import requests
from celery import shared_task

from telegram_bot.models import TelegramUser

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def reply_to_message(self, telegram_user_id: int, message_id: int, text: str):
    """Reply to a user's message, showing "typing" first.

    Network errors and 5xx replies are retried. A 429 is retried after the
    number of seconds Telegram gives in retry_after. Other 4xx replies, such
    as 403 when the user blocked the bot, are logged and dropped, since a
    retry would get the same answer.
    """
    try:
        telegram_user = TelegramUser.objects.get(pk=telegram_user_id)
    except TelegramUser.DoesNotExist:
        logger.warning("TelegramUser %s not found, skipping reply", telegram_user_id)
        return

    try:
        telegram_user.send_chat_action("typing")
    except requests.RequestException:
        logger.info("Could not send chat action to %s", telegram_user.telegram_id)

    try:
        response = telegram_user.send_message(text, reply_to_message_id=message_id)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise self.retry(exc=e) from e

    if response.ok:
        return

    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        try:
            retry_after = int(response.json()["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError):
            retry_after = None
        raise self.retry(countdown=retry_after)

    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise self.retry()

    logger.warning(
        "Telegram rejected reply to %s (status %s): %s",
        telegram_user.telegram_id,
        response.status_code,
        response.text[:500],
    )
