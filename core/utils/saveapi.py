import logging
from typing import Any

import requests
from django.core.exceptions import ImproperlyConfigured

from core.utils.core_api import send_logged_request
from settings.models import CoreAPISetting

logger = logging.getLogger(__name__)


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
        requests.RequestException: If request fails
    """
    endpoint = f"{get_saveapi_url().rstrip('/')}/v1/download"
    response = send_logged_request(
        get_saveapi_session(),
        "GET",
        endpoint,
        params={"url": url},
        timeout=timeout,
    )
    return response.json()


def fetch_user_stories(username: str) -> dict[str, Any]:
    """Fetch the active stories of an Instagram user through SaveAPI."""
    logger.info("Fetching stories from SaveAPI for username: %s", username)
    return download(f"https://www.instagram.com/stories/{username}/")
