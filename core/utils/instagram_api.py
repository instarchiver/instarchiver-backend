import logging
from typing import Any

from .core_api import make_request

logger = logging.getLogger(__name__)


def fetch_user_info_by_username_v2(username: str) -> dict[str, Any]:
    """Fetch Instagram user information by username using Core API v1 endpoint.

    Args:
        username: Instagram username to fetch information for

    Returns:
        Dictionary containing user information from the API response

    Raises:
        ImproperlyConfigured: If API settings are not configured
        requests.RequestException: If the API request fails
    """
    endpoint = "/api/v1/instagram/v1/fetch_user_info_by_username"
    params = {"username": username}

    logger.info("Fetching user info for username: %s", username)

    try:
        response = make_request("GET", endpoint, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.exception("Failed to fetch user info for username %s: %s", username, e)  # noqa: TRY401
        raise
    else:
        logger.info("Successfully fetched user info for username: %s", username)
        return data


def fetch_user_info_by_user_id(user_id: str) -> dict[str, Any]:
    """Fetch Instagram user information by user ID using Core API v1 endpoint.

    Args:
        user_id: Instagram user ID to fetch information for

    Returns:
        Dictionary containing user information from the API response

    Raises:
        ImproperlyConfigured: If API settings are not configured
        requests.RequestException: If the API request fails
    """
    endpoint = "/api/v1/instagram/v1/fetch_user_info_by_id"
    params = {"user_id": user_id}

    logger.info("Fetching user info for user_id: %s", user_id)

    try:
        response = make_request("GET", endpoint, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.exception("Failed to fetch user info for user_id %s: %s", user_id, e)  # noqa: TRY401
        raise
    else:
        logger.info("Successfully fetched user info for user_id: %s", user_id)
        return data


def fetch_user_posts_by_username(
    username: str,
    max_id: str | None = None,
) -> dict[str, Any]:
    """Fetch Instagram user posts by username with pagination support.

    Args:
        username: Instagram username to fetch posts for
        max_id: Optional pagination cursor for fetching next page of posts

    Returns:
        Dictionary containing user posts from the API response:
        - data.items: List of posts
        - data.next_max_id: Cursor for next page (if available)

    Raises:
        ImproperlyConfigured: If API settings are not configured
        requests.RequestException: If the API request fails
    """
    endpoint = "/api/v1/instagram/v1/fetch_user_posts"
    params = {"user_id": username, "count": 50}
    if max_id:
        params["max_id"] = max_id

    logger.info(
        "Fetching posts for user_id: %s (max_id: %s)",
        username,
        max_id or "None",
    )

    try:
        response = make_request("GET", endpoint, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.exception("Failed to fetch posts for user_id %s: %s", username, e)  # noqa: TRY401
        raise
    else:
        logger.info("Successfully fetched posts for user_id: %s", username)
        return data


def fetch_post_by_id(post_id: str) -> dict[str, Any]:
    """Fetch Instagram post details by post ID using Core API v1 endpoint.

    Args:
        post_id: Instagram post ID to fetch details for

    Returns:
        Dictionary containing post details from the API response

    Raises:
        ImproperlyConfigured: If API settings are not configured
        requests.RequestException: If the API request fails
    """
    endpoint = "/api/v1/instagram/v1/fetch_post_by_id"
    params = {"post_id": post_id}

    logger.info("Fetching post details for post_id: %s", post_id)

    try:
        response = make_request("GET", endpoint, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.exception("Failed to fetch post details for post_id %s: %s", post_id, e)  # noqa: TRY401
        raise
    else:
        logger.info("Successfully fetched post details for post_id: %s", post_id)
        return data
