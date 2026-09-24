from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db import transaction
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    import requests


class TelegramUser(models.Model):
    """A Telegram user who has talked to the bot, linked 1:1 to a Django user.

    Saving a TelegramUser without a user creates a Django user for it.
    The reverse doesn't happen: a new Django user gets no TelegramUser.

    bulk_create() bypasses save(), so every row must already have a user or
    the insert fails on the NOT NULL column. If two requests create the same
    telegram_id at the same time, one of them raises IntegrityError. Use
    get_or_create(telegram_id=...) and retry once when that happens.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_user",
        blank=True,
    )
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=32, blank=True, default="")
    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64, blank=True, default="")
    language_code = models.CharField(max_length=35, blank=True, default="")
    is_bot = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Telegram User"
        verbose_name_plural = "Telegram Users"

    def __str__(self) -> str:
        if self.username:
            return f"@{self.username}"
        return f"{self.first_name} ({self.telegram_id})"

    def save(self, *args, **kwargs):
        if self.user_id is not None:
            super().save(*args, **kwargs)
            return

        with transaction.atomic(using=kwargs.get("using")):
            self.user = self._create_django_user()
            super().save(*args, **kwargs)

    def _create_django_user(self):
        # Always create a new user. Reusing an existing "telegram_<id>" account
        # would hand this Telegram identity to whoever registered that name.
        user = get_user_model()(
            username=f"telegram_{self.telegram_id}",
            name=f"{self.first_name} {self.last_name}".strip(),
        )
        user.set_unusable_password()
        user.save()
        return user

    # Bot API calls. The bot only talks in private chats, where the chat id is
    # the user's Telegram id.

    def send_message(self, text: str, reply_to_message_id: int) -> "requests.Response":
        """Send text as a reply to one of the user's messages.

        The message id is required so every bot message replies to something
        the user sent. If that message was deleted, the text is still sent,
        just not as a reply.
        """

        from telegram_bot.utils import call_telegram_api  # noqa: PLC0415

        return call_telegram_api(
            "sendMessage",
            {
                "chat_id": self.telegram_id,
                "text": text,
                "reply_parameters": {
                    "message_id": reply_to_message_id,
                    "allow_sending_without_reply": True,
                },
            },
        )

    def send_chat_action(self, action: str = "typing") -> "requests.Response":
        """Show a status like "typing" in the chat.

        Telegram clears it after 5 seconds or when the bot sends a message.
        """

        from telegram_bot.utils import call_telegram_api  # noqa: PLC0415

        return call_telegram_api(
            "sendChatAction",
            {"chat_id": self.telegram_id, "action": action},
        )
