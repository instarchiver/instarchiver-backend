from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db import transaction
from simple_history.models import HistoricalRecords


class TelegramUser(models.Model):
    """A Telegram user who has talked to the bot, linked 1:1 to a Django user.

    Saving a TelegramUser with no ``user`` creates a Django user for it.
    Creating a Django user does not create a TelegramUser.

    ``bulk_create()`` skips ``save()``, so it fails on the NOT NULL ``user``
    column unless every row already has a user. Two first saves for the same
    ``telegram_id`` at once raise IntegrityError. Callers should use
    ``get_or_create(telegram_id=...)`` and retry once.
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
