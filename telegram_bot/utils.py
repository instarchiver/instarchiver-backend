import logging
import time
from typing import Any

import requests
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.db import transaction

from api_logs.models import APIRequestLog
from settings.models import TelegramSetting
from telegram_bot.models import TelegramUser

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
MASKED_TOKEN = "***"  # noqa: S105

# Telegram "User" object field -> (TelegramUser field, default)
USER_FIELD_MAP = {
    "username": ("username", ""),
    "first_name": ("first_name", ""),
    "last_name": ("last_name", ""),
    "language_code": ("language_code", ""),
    "is_bot": ("is_bot", False),
    "is_premium": ("is_premium", False),
}


class TelegramUserConflict(Exception):  # noqa: N818
    """Raised when a TelegramUser can't be created or fetched for a Telegram id.

    This happens when another Django user already has the username
    telegram_<id>. TelegramUser deliberately never reuses that account.
    """


def _mask(value: str, token: str) -> str:
    return value.replace(token, MASKED_TOKEN) if token else value


def call_telegram_api(
    method: str,
    payload: dict[str, Any],
    bot_token: str | None = None,
    timeout: int = 10,
) -> requests.Response:
    """POST the payload to a Bot API method and log the call to APIRequestLog.

    The bot token shows up as *** in everything that gets logged. The response
    comes back as is, without raise_for_status(), so the caller decides what
    to do with 4xx and 5xx replies.

    Args:
        method: Bot API method name, e.g. sendMessage
        payload: JSON body
        bot_token: Token to use. Defaults to TelegramSetting.bot_token
        timeout: Request timeout in seconds

    Raises:
        ImproperlyConfigured: If no bot token is set
        requests.RequestException: If the request can't be sent
    """
    token = bot_token if bot_token is not None else TelegramSetting.get_solo().bot_token
    if not token:
        msg = "Telegram bot token is not configured"
        raise ImproperlyConfigured(msg)

    # Keep the full URL out of locals so error reports with frame variables
    # (e.g. Sentry) only ever see the masked one.
    masked_url = f"{TELEGRAM_API_BASE_URL}/bot{MASKED_TOKEN}/{method}"
    api_log = APIRequestLog.objects.create(
        method="POST",
        url=masked_url,
        request_body=payload,
        status=APIRequestLog.STATUS_PENDING,
    )
    start_time = time.time()

    try:
        response = requests.post(
            masked_url.replace(MASKED_TOKEN, token, 1),
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as e:
        api_log.status = (
            APIRequestLog.STATUS_TIMEOUT
            if isinstance(e, requests.Timeout)
            else APIRequestLog.STATUS_ERROR
        )
        api_log.duration_ms = int((time.time() - start_time) * 1000)
        api_log.error_message = _mask(str(e), token)
        api_log.save()
        logger.warning("Telegram %s failed: %s", method, api_log.error_message)
        # Drop the original exception: its message and traceback carry the URL.
        raise type(e)(api_log.error_message) from None

    api_log.response_status_code = response.status_code
    api_log.response_headers = dict(response.headers)
    api_log.duration_ms = int((time.time() - start_time) * 1000)
    api_log.status = (
        APIRequestLog.STATUS_SUCCESS if response.ok else APIRequestLog.STATUS_ERROR
    )
    try:
        api_log.response_body = response.json()
    except ValueError:
        api_log.response_body = {"raw_content": _mask(response.text[:1000], token)}
    api_log.save()

    return response


def _user_fields_from_telegram(data: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for key, (field_name, default) in USER_FIELD_MAP.items():
        value = data.get(key) or default
        if isinstance(value, str):
            field = TelegramUser._meta.get_field(field_name)  # noqa: SLF001
            value = value[: getattr(field, "max_length", None)]
        fields[field_name] = value
    if not fields["first_name"]:
        fields["first_name"] = str(data["id"])
    return fields


def upsert_telegram_user(data: dict[str, Any]) -> TelegramUser:
    """Create or update a TelegramUser from the "from" field of a Telegram message.

    It only saves when a field changed, so repeat messages from the same user
    don't add history rows. A name change is copied to the linked Django user.

    Raises:
        TelegramUserConflict: If another Django user already has the username
            telegram_<id>
    """
    telegram_id = data["id"]
    fields = _user_fields_from_telegram(data)

    try:
        with transaction.atomic():
            telegram_user, created = TelegramUser.objects.get_or_create(
                telegram_id=telegram_id,
                defaults=fields,
            )
    except IntegrityError as e:
        # Either another request created the row first, or telegram_<id> is
        # already taken by another Django user.
        try:
            telegram_user = TelegramUser.objects.get(telegram_id=telegram_id)
        except TelegramUser.DoesNotExist:
            msg = f"Could not create TelegramUser for telegram_id={telegram_id}"
            raise TelegramUserConflict(msg) from e
        created = False

    if created:
        return telegram_user

    changed = [
        name for name, value in fields.items() if getattr(telegram_user, name) != value
    ]
    if not changed:
        return telegram_user

    for name in changed:
        setattr(telegram_user, name, fields[name])
    telegram_user.save(update_fields=[*changed, "updated_at"])

    if {"first_name", "last_name"} & set(changed):
        user = telegram_user.user
        user.name = f"{telegram_user.first_name} {telegram_user.last_name}".strip()
        user.save(update_fields=["name"])

    return telegram_user


def parse_command(text: str | None) -> str | None:
    """Return the command in lowercase, without arguments or a bot mention.

    /start, /start ref_123 and /start@MyBot all return "start". Text that
    isn't a command returns None.
    """

    if not text or not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return None
    return parts[0].split("@", 1)[0].lower() or None
