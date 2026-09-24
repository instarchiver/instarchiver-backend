import pytest
from django.db import IntegrityError
from django.db import transaction

from core.users.models import User
from core.users.tests.factories import UserFactory
from telegram_bot.models import TelegramUser
from telegram_bot.tests.factories import TelegramUserFactory

pytestmark = pytest.mark.django_db


def test_creating_telegram_user_creates_django_user():
    telegram_user = TelegramUserFactory.create(
        telegram_id=123456789,
        first_name="Budi",
        last_name="Santoso",
    )

    user = telegram_user.user
    assert user.pk is not None
    assert user.username == "telegram_123456789"
    assert user.name == "Budi Santoso"
    assert not user.has_usable_password()
    assert TelegramUser.objects.get(user=user) == telegram_user


def test_name_without_last_name_is_stripped():
    telegram_user = TelegramUserFactory.create(first_name="Budi", last_name="")

    assert telegram_user.user.name == "Budi"


def test_existing_user_is_linked_without_creating_another():
    user = UserFactory.create()
    user_count = User.objects.count()

    telegram_user = TelegramUserFactory.create(user=user)

    assert telegram_user.user == user
    assert User.objects.count() == user_count


def test_creating_django_user_does_not_create_telegram_user():
    UserFactory.create()

    assert not TelegramUser.objects.exists()


def test_resave_does_not_create_another_user():
    telegram_user = TelegramUserFactory.create()
    user_count = User.objects.count()

    telegram_user.first_name = "Changed"
    telegram_user.save()

    assert User.objects.count() == user_count


def test_one_django_user_cannot_have_two_telegram_users():
    telegram_user = TelegramUserFactory.create()

    with pytest.raises(IntegrityError), transaction.atomic():
        TelegramUserFactory.create(user=telegram_user.user)


def test_duplicate_telegram_id_rolls_back_user_creation():
    TelegramUserFactory.create(telegram_id=42)
    user_count = User.objects.count()

    with pytest.raises(IntegrityError), transaction.atomic():
        TelegramUserFactory.create(telegram_id=42)

    assert User.objects.count() == user_count


def test_existing_username_is_not_reused():
    UserFactory.create(username="telegram_777")

    with pytest.raises(IntegrityError), transaction.atomic():
        TelegramUserFactory.create(telegram_id=777)

    assert not TelegramUser.objects.filter(telegram_id=777).exists()


def test_deleting_django_user_cascades():
    telegram_user = TelegramUserFactory.create()

    telegram_user.user.delete()

    assert not TelegramUser.objects.filter(pk=telegram_user.pk).exists()


def test_deleting_telegram_user_keeps_django_user():
    telegram_user = TelegramUserFactory.create()
    user_pk = telegram_user.user.pk

    telegram_user.delete()

    assert User.objects.filter(pk=user_pk).exists()


def test_str():
    assert str(TelegramUserFactory.build(username="budi")) == "@budi"
    assert (
        str(TelegramUserFactory.build(username="", first_name="Budi", telegram_id=5))
        == "Budi (5)"
    )
