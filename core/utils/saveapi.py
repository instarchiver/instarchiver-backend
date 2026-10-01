import logging

import requests
from django.core.exceptions import ImproperlyConfigured

from core.utils.core_api import send_logged_request
from settings.models import CoreAPISetting

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_ERROR_CODES = {"RATE_LIMITED"}


class SaveAPIError(Exception):
    """Error returned by SaveAPI.

    Attributes:
        code (str): SaveAPI error code, or HTTP_<status> when the body has none
        status_code (int or None): HTTP status of the response
        retryable (bool): True if the call is worth retrying
        retry_after (int or None): seconds from the Retry-After header
    """

    def __init__(
        self,
        code,
        message,
        *,
        status_code=None,
        retryable=False,
        retry_after=None,
    ):
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(f"SaveAPI error {code}: {message}")

    @property
    def is_rate_limited(self):
        """True if SaveAPI refused the request because of its rate limit."""
        return self.status_code == 429 or self.code == "RATE_LIMITED"  # noqa: PLR2004


def is_retryable_error(exc):
    """Return True (bool) if a SaveAPI call that raised exc is worth retrying."""
    if isinstance(exc, SaveAPIError):
        return exc.retryable
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def _error_from_http_error(exc):
    """Build a SaveAPIError from a requests.HTTPError, using the JSON body if any."""
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

    retry_after = (
        response.headers.get("Retry-After", "") if response is not None else ""
    )
    return SaveAPIError(
        code,
        message,
        status_code=status_code,
        retryable=status_code in RETRYABLE_STATUS or code in RETRYABLE_ERROR_CODES,
        retry_after=int(retry_after) if retry_after.isdigit() else None,
    )


def get_saveapi_url():
    """Return the SaveAPI base URL (str) from settings.

    Raises:
        ImproperlyConfigured: if the URL is not set
    """
    setting = CoreAPISetting.get_solo()
    if not setting.saveapi_url:
        msg = "SaveAPI URL is not configured in settings"
        raise ImproperlyConfigured(msg)
    return setting.saveapi_url


def get_saveapi_session():
    """Return a requests.Session authenticated with the SaveAPI key.

    Raises:
        ImproperlyConfigured: if the API key is not set
    """
    setting = CoreAPISetting.get_solo()
    if not setting.saveapi_api_key:
        msg = "SaveAPI API key is not configured in settings"
        raise ImproperlyConfigured(msg)

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {setting.saveapi_api_key}"})
    return session


def _get(path, params=None, timeout=30):
    """GET a SaveAPI endpoint and return the parsed JSON (dict).

    Args:
        path (str): endpoint path, e.g. /v1/me
        params (dict or None): query parameters
        timeout (int): request timeout in seconds

    Raises:
        ImproperlyConfigured: if SaveAPI settings are missing
        SaveAPIError: if SaveAPI answers with an HTTP error status
        requests.RequestException: if the request fails before a response
    """
    url = f"{get_saveapi_url().rstrip('/')}{path}"
    try:
        response = send_logged_request(
            get_saveapi_session(),
            "GET",
            url,
            params=params,
            timeout=timeout,
        )
    except requests.HTTPError as e:
        raise _error_from_http_error(e) from e
    return response.json()


def download(url, timeout=60):
    """Resolve a public media URL (str), such as a story URL, via /v1/download.

    Returns the parsed JSON (dict). Raises the same errors as _get().
    """
    return _get("/v1/download", {"url": url}, timeout)


def get_me(timeout=15):
    """Return the key, plan and credit details (dict) for the configured key."""
    return _get("/v1/me", timeout=timeout)


def fetch_user_profile(username, timeout=30):
    """Fetch the public profile (dict) of an Instagram username (str)."""
    logger.info("Fetching profile from SaveAPI for username: %s", username)
    return _get("/v1/instagram/profile", {"username": username}, timeout)


def fetch_user_stories(username):
    """Fetch the active stories (dict) of an Instagram username (str)."""
    logger.info("Fetching stories from SaveAPI for username: %s", username)
    return download(f"https://www.instagram.com/stories/{username}/")
