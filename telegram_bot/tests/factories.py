from factory import Faker
from factory import Sequence
from factory.django import DjangoModelFactory

from telegram_bot.models import TelegramUser


class TelegramUserFactory(DjangoModelFactory[TelegramUser]):
    """Builds TelegramUser rows. Leaves ``user`` unset so save() creates one."""

    telegram_id = Sequence(lambda n: 100_000_000 + n)
    username = Faker("user_name")
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    language_code = "en"

    class Meta:
        model = TelegramUser
