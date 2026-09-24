import logging
from typing import Any

import requests
from django.core.exceptions import ImproperlyConfigured

from core.utils.core_api import send_logged_request
from settings.models import CoreAPISetting

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_ERROR_CODES = {"RATE_LIMITED"}


class SaveAPIError(Exception):
    """Error returned by SaveAPI, with its error code and retry hint."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(f"SaveAPI error {code}: {message}")


def is_retryable_error(exc: BaseException) -> bool:
    """Return True if a SaveAPI call that raised ``exc`` is worth retrying."""
    if isinstance(exc, SaveAPIError):
        return exc.retryable
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def _error_from_http_error(exc: requests.HTTPError) -> SaveAPIError:
    """Build a SaveAPIError from an HTTP error, using the JSON body if present."""
    response = exc.response
    status_code = response.status_code if response is not None else None
    code = f"HTTP_{status_code}" if status_code else "HTTP_ERROR"
    message = str(exc)

    if response is not None:
        try:
            error = response.json().get("error") or {}
        except (ValueError, AttributeError):
            error = {}
        if isinstance(error, dict):
            code = error.get("code") or code
            message = error.get("message") or message

    return SaveAPIError(
        code,
        message,
        status_code=status_code,
        retryable=status_code in RETRYABLE_STATUS or code in RETRYABLE_ERROR_CODES,
    )


def get_saveapi_url() -> str:
    """Retrieve SaveAPI base URL from settings."""
    setting = CoreAPISetting.get_solo()
    if not setting.saveapi_url:
        msg = "SaveAPI URL is not configured in settings"
        raise ImproperlyConfigured(msg)
    return setting.saveapi_url


def get_saveapi_session() -> requests.Session:
    """Return a requests session authenticated with the SaveAPI key."""
    setting = CoreAPISetting.get_solo()
    if not setting.saveapi_api_key:
        msg = "SaveAPI API key is not configured in settings"
        raise ImproperlyConfigured(msg)

    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {setting.saveapi_api_key}"},
    )
    return session


def download(url: str, timeout: int = 60) -> dict[str, Any]:
    """Resolve a public media URL through the SaveAPI download endpoint.

    Args:
        url: Public link to resolve, such as an Instagram story URL
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response from SaveAPI

    Raises:
        ImproperlyConfigured: If SaveAPI settings are not configured
        SaveAPIError: If SaveAPI answers with an HTTP error status
        requests.RequestException: If the request fails before a response
    """
    endpoint = f"{get_saveapi_url().rstrip('/')}/v1/download"
    try:
        response = send_logged_request(
            get_saveapi_session(),
            "GET",
            endpoint,
            params={"url": url},
            timeout=timeout,
        )
    except requests.HTTPError as e:
        raise _error_from_http_error(e) from e
    return response.json()


def fetch_user_stories(username: str) -> dict[str, Any]:
    """Fetch the active stories of an Instagram user through SaveAPI."""
    logger.info("Fetching stories from SaveAPI for username: %s", username)
    return download(f"https://www.instagram.com/stories/{username}/")
