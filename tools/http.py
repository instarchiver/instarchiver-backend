from dataclasses import dataclass

from curl_cffi import CurlOpt
from curl_cffi.requests import Response
from curl_cffi.requests import Session
from curl_cffi.requests import exceptions as curl_exceptions

from settings.models import ProxySetting
from tools.constants import DEFAULT_MAX_ATTEMPTS
from tools.constants import DEFAULT_MAX_HTML_BYTES
from tools.constants import DEFAULT_TIMEOUT
from tools.constants import PROXY_CREDENTIALS_RE
from tools.constants import TRANSIENT_FETCH_ERRORS


class HttpFetchError(Exception):
    """Error raised when an upstream HTTP fetch fails."""


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Proxy URL and TLS verification settings for HTTP requests."""

    url: str | None = None
    verify_ssl: bool = True

    @classmethod
    def from_settings(cls) -> "ProxyConfig":
        """Build a ProxyConfig from the stored ProxySetting singleton."""
        setting = ProxySetting.get_solo()
        url = setting.proxy_url.strip() or None
        return cls(url=url, verify_ssl=setting.verify_ssl)

    @property
    def clean_url(self) -> str | None:
        return self.url.strip() or None if self.url else None


def _sanitize_error_message(message: str, proxy_url: str | None) -> str:
    """Strip proxy credentials from an error message before returning or logging."""
    sanitized = message.replace(proxy_url, "[proxy]") if proxy_url else message
    return PROXY_CREDENTIALS_RE.sub("://***@", sanitized)


def _read_limited_text(response: Response) -> str:
    """Read a streaming response up to DEFAULT_MAX_HTML_BYTES as UTF-8."""
    chunks: list[bytes] = []
    total_bytes = 0
    for chunk in response.iter_content():
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > DEFAULT_MAX_HTML_BYTES:
            msg = "Upstream response exceeded the maximum allowed size."
            raise HttpFetchError(msg)
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _raise_sanitized_error(exc: Exception, proxy_url: str | None) -> None:
    """Raise HttpFetchError with proxy credentials stripped from the message."""
    raise HttpFetchError(_sanitize_error_message(str(exc), proxy_url)) from exc


def fetch_page(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    proxy: ProxyConfig | None = None,
) -> tuple[int, str, str]:
    """Fetch a web page with Chrome TLS impersonation and optional ProxySetting."""
    resolved = proxy if proxy is not None else ProxyConfig.from_settings()
    proxy_url = resolved.clean_url

    with Session(impersonate="chrome", trust_env=False, max_redirects=5) as session:
        if proxy_url and not resolved.verify_ssl:
            session.curl.setopt(CurlOpt.PROXY_SSL_VERIFYPEER, 0)
            session.curl.setopt(CurlOpt.PROXY_SSL_VERIFYHOST, 0)

        for attempt in range(DEFAULT_MAX_ATTEMPTS):
            response = None
            try:
                response = session.get(
                    url,
                    headers=headers or {},
                    proxy=proxy_url,
                    timeout=DEFAULT_TIMEOUT,
                    verify=resolved.verify_ssl,
                    allow_redirects=True,
                    stream=True,
                )
                html = _read_limited_text(response)
                return (
                    int(response.status_code),
                    str(getattr(response, "url", "") or ""),
                    html,
                )
            except curl_exceptions.SSLError as exc:
                _raise_sanitized_error(exc, proxy_url)
            except TRANSIENT_FETCH_ERRORS as exc:
                if attempt == DEFAULT_MAX_ATTEMPTS - 1:
                    _raise_sanitized_error(exc, proxy_url)
            except curl_exceptions.RequestException as exc:
                _raise_sanitized_error(exc, proxy_url)
            finally:
                if response is not None and hasattr(response, "close"):
                    response.close()

    msg = "Failed to fetch upstream page."
    raise HttpFetchError(msg)
