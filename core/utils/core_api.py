import logging
import time
from typing import Any

import requests

from api_logs.models import APIRequestLog

logger = logging.getLogger(__name__)


def _redact_headers(headers) -> dict[str, Any]:
    """Return a copy of the headers with credentials masked for logging."""
    return {
        key: "***" if key.lower() == "authorization" else value
        for key, value in headers.items()
    }


def send_logged_request(  # noqa: PLR0913
    session: requests.Session,
    method: str,
    url: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
) -> requests.Response:
    """Send an HTTP request and record it in APIRequestLog.

    Args:
        session: Session with auth headers already set
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        url: Full request URL
        data: Request payload for POST/PUT requests
        params: Query parameters
        timeout: Request timeout in seconds

    Returns:
        Response object

    Raises:
        requests.RequestException: If request fails
    """
    # Create log entry
    api_log = APIRequestLog.objects.create(
        method=method.upper(),
        url=url,
        request_headers=_redact_headers(session.headers),
        request_params=params or {},
        request_body=data or {},
        status=APIRequestLog.STATUS_PENDING,
    )

    start_time = time.time()

    try:
        response = session.request(
            method=method.upper(),
            url=url,
            json=data,
            params=params,
            timeout=timeout,
        )

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Update log with success
        api_log.response_status_code = response.status_code
        api_log.response_headers = dict(response.headers)
        api_log.duration_ms = duration_ms
        api_log.status = APIRequestLog.STATUS_SUCCESS

        try:
            api_log.response_body = response.json()
        except ValueError:
            api_log.response_body = {"raw_content": response.text[:1000]}

        api_log.save()

        response.raise_for_status()
        return response  # noqa: TRY300

    except requests.exceptions.Timeout as e:
        duration_ms = int((time.time() - start_time) * 1000)
        api_log.status = APIRequestLog.STATUS_TIMEOUT
        api_log.duration_ms = duration_ms
        api_log.error_message = str(e)
        api_log.save()
        logger.exception("API request timeout: %s", e)  # noqa: TRY401
        raise

    except requests.RequestException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        api_log.status = APIRequestLog.STATUS_ERROR
        api_log.duration_ms = duration_ms
        api_log.error_message = str(e)

        if hasattr(e, "response") and e.response is not None:
            api_log.response_status_code = e.response.status_code
            api_log.response_headers = dict(e.response.headers)
            try:
                api_log.response_body = e.response.json()
            except ValueError:
                api_log.response_body = {"raw_content": e.response.text[:1000]}

        api_log.save()
        logger.exception("API request failed: %s", e)  # noqa: TRY401
        raise
