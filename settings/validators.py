from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

ALLOWED_PROXY_SCHEMES = frozenset(
    {"http", "https", "socks4", "socks4a", "socks5", "socks5h"},
)


def validate_proxy_url(value: str) -> None:
    """Validate that a non-empty proxy URL uses a supported scheme and host."""
    cleaned = value.strip()
    if not cleaned:
        return
    try:
        parsed = urlsplit(cleaned)
        _ = parsed.port
    except ValueError as exc:
        msg = "Enter a valid proxy URL."
        raise ValidationError(msg) from exc

    if parsed.scheme.lower() not in ALLOWED_PROXY_SCHEMES or not parsed.hostname:
        msg = (
            "Proxy URL must include a hostname and use one of: "
            "http, https, socks4, socks4a, socks5, socks5h."
        )
        raise ValidationError(msg)
