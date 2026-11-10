import logging
from typing import Any

from .core_api import make_request

logger = logging.getLogger(__name__)


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
