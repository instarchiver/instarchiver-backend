import hmac
import logging

from django.core.cache import cache
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from settings.models import TelegramSetting
from telegram_bot.models import TelegramUser
from telegram_bot.tasks import reply_to_message
from telegram_bot.utils import parse_command
from telegram_bot.utils import upsert_telegram_user

logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"  # noqa: S105
UPDATE_CACHE_TTL = 60 * 60 * 24
FALLBACK_REPLY = "Sorry, I don't support that command yet. Send /start to begin."


@extend_schema(exclude=True)
class TelegramWebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """Receive a Telegram update, sync the sender and queue a reply.

        Returns 200 for every authenticated request, even ones that fail,
        because Telegram keeps resending an update until it gets a 2xx.
        """
        if not self._has_valid_secret(request):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            # Savepoint, so a failure here doesn't break the request transaction.
            with transaction.atomic():
                self._handle_update(request.data)
        except Exception:
            logger.exception("Failed to handle Telegram update")

        return Response({"status": "ok"})

    def _has_valid_secret(self, request) -> bool:
        expected = TelegramSetting.get_solo().webhook_secret
        received = request.headers.get(SECRET_HEADER, "")
        if not expected or not received:
            return False
        return hmac.compare_digest(received.encode(), expected.encode())

    def _handle_update(self, update: dict) -> None:
        if self._is_duplicate_update(update):
            return

        message = self._get_private_message(update)
        if message is None:
            return

        telegram_user = upsert_telegram_user(message["from"])

        command = parse_command(message.get("text"))
        handler = {
            "start": self.handle_start,
        }.get(command or "", self.handle_unknown)
        handler(telegram_user, message)

    def _is_duplicate_update(self, update: dict) -> bool:
        """Return True if this update_id was already seen in the last 24 hours."""

        update_id = update.get("update_id")
        if update_id is None:
            return False

        if cache.add(f"telegram:update:{update_id}", 1, UPDATE_CACHE_TTL):
            return False

        logger.info("Skipping duplicate Telegram update %s", update_id)
        return True

    def _get_private_message(self, update: dict) -> dict | None:
        """Return the update's message if a person sent it in a private chat.

        Returns None for other update types, group chats, bot senders and
        messages sent through another bot.
        """

        message = update.get("message")
        if not message:
            return None

        sender = message.get("from")
        if (
            not sender
            or sender.get("is_bot")
            or message.get("chat", {}).get("type") != "private"
            or message.get("via_bot")
        ):
            return None

        return message

    def handle_start(self, telegram_user: TelegramUser, message: dict) -> None:
        """Greet the user when they send /start, with or without a payload."""

        self._reply(
            telegram_user,
            message,
            f"Hi {telegram_user.first_name}! Welcome to Instarchiver.",
        )

    def handle_unknown(self, telegram_user: TelegramUser, message: dict) -> None:
        """Handle plain text, unknown commands and messages without text."""
        self._reply(telegram_user, message, FALLBACK_REPLY)

    def _reply(self, telegram_user: TelegramUser, message: dict, text: str) -> None:
        """Send text as a reply to the user's message after the transaction commits."""

        # Read these now so a bad payload fails inside the savepoint in post(),
        # not in the on_commit callback, which runs after post() returns.
        telegram_user_pk = telegram_user.pk
        message_id = message["message_id"]

        def queue_reply():
            try:
                reply_to_message.delay(telegram_user_pk, message_id, text)
            except Exception:
                logger.exception("Failed to queue Telegram reply")

        transaction.on_commit(queue_reply)
