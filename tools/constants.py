import re

from curl_cffi.requests import exceptions as curl_exceptions

# Instagram usernames are 1-30 chars of ASCII letters, digits, dots, or underscores.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# Matches user:pass@ credentials embedded in proxy URLs so errors can be redacted.
PROXY_CREDENTIALS_RE = re.compile(r"://[^/@\s]+@")

# Connect and read timeouts in seconds for a single upstream HTTP attempt.
DEFAULT_TIMEOUT = (5, 10)

# Maximum fetch attempts for transient network or rotating-proxy failures.
DEFAULT_MAX_ATTEMPTS = 2

# Cap streamed HTML responses at 5 MiB to avoid exhausting worker memory.
DEFAULT_MAX_HTML_BYTES = 5 * 1024 * 1024

# Upper bound matching PostgreSQL 32-bit PositiveIntegerField capacity.
MAX_POSITIVE_INT32 = 2_147_483_647

# Network and proxy exceptions safe to retry; SSL and HTTP errors fail immediately.
TRANSIENT_FETCH_ERRORS = (
    curl_exceptions.Timeout,
    curl_exceptions.ConnectionError,
    curl_exceptions.ProxyError,
)

# Suffix multipliers used by Instagram OpenGraph meta descriptions (e.g. "272M").
COUNT_MULTIPLIERS = {
    "": 1,
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
}

# Forces English OpenGraph counts so Followers/Following/Posts labels match.
PROFILE_HEADERS = {"Accept-Language": "en-US,en;q=0.9"}

# Machine-readable error codes returned in InstagramProfileError responses.
ERROR_INVALID_USERNAME = "INVALID_USERNAME"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_LOGIN_WALL = "LOGIN_WALL"
ERROR_UPSTREAM = "UPSTREAM_ERROR"
