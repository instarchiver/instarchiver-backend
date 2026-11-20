import json
import logging
import re
from collections.abc import Iterator
from html import unescape
from http import HTTPStatus
from urllib.parse import urlsplit

from tools.constants import COUNT_MULTIPLIERS
from tools.constants import ERROR_INVALID_USERNAME
from tools.constants import ERROR_LOGIN_WALL
from tools.constants import ERROR_RATE_LIMITED
from tools.constants import ERROR_UPSTREAM
from tools.constants import MAX_POSITIVE_INT32
from tools.constants import PROFILE_HEADERS
from tools.constants import USERNAME_RE
from tools.http import HttpFetchError
from tools.http import ProxyConfig
from tools.http import fetch_page

logger = logging.getLogger(__name__)


class InstagramProfileError(Exception):
    """Error raised while fetching or parsing an Instagram profile page."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = HTTPStatus.BAD_GATEWAY,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def safe_positive_int(value: object) -> int | None:
    """Convert value to a 32-bit non-negative int, or return None if invalid."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return min(parsed, MAX_POSITIVE_INT32)


def _iter_embedded_json_dicts(html: str, key: str) -> Iterator[dict]:
    """Yield decoded JSON dicts following each occurrence of '"<key>":' in HTML."""
    decoder = json.JSONDecoder()
    for match in re.finditer(rf'"{re.escape(key)}":', html):
        try:
            decoded, _ = decoder.raw_decode(html, match.end())
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            yield decoded


def _iter_connection_nodes(user: dict, key: str) -> Iterator[dict]:
    """Yield dict nodes from a Relay GraphQL connection edge list."""
    connection = user.get(key)
    edges = connection.get("edges") if isinstance(connection, dict) else None
    if not isinstance(edges, list):
        return
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            yield node


def _meta(html: str, key: str) -> str | None:
    """Extract a meta tag content value by property or name attribute."""
    match = re.search(
        rf'<meta (?=[^>]*(?:property|name)="{re.escape(key)}")[^>]*content="([^"]*)"',
        html,
    )
    return unescape(match.group(1)) if match else None


def _parse_count(text: str, label: str) -> int | None:
    """Parse follower, following, or post counts from og:description text."""
    # shortcut: og:description rounds large numbers (e.g. "272M Followers").
    match = re.search(
        rf"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*([KMB]?)\s+{re.escape(label)}\b",
        text,
    )
    if not match:
        return None
    try:
        numeric = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return safe_positive_int(round(numeric * COUNT_MULTIPLIERS[match.group(2)]))


def _extract_username_from_og_url(og_url: str | None) -> str | None:
    """Extract an Instagram username from og:url only when the host is instagram.com."""
    if not og_url:
        return None
    parsed = urlsplit(og_url)
    host = (parsed.hostname or "").lower()
    if host != "instagram.com" and not host.endswith(".instagram.com"):
        return None
    segment = parsed.path.strip("/").split("/", maxsplit=1)[0]
    return segment if segment and USERNAME_RE.match(segment) else None


def _fallback_user_from_meta(
    html: str,
    og_description: str,
    requested_username: str | None,
) -> dict | None:
    """Build a minimal user dict from meta tags for age-gated profiles."""
    # shortcut: JS challenge shells without Relay JSON or meta tags
    # look identical to missing profiles while logged out.
    if not og_description:
        return None
    profile_id = re.search(r'"profile_id":"(\d+)"', html)
    bio = re.search(
        r' on Instagram: "(.*)"$',
        _meta(html, "description") or "",
        re.DOTALL,
    )
    og_title = _meta(html, "og:title") or ""
    return {
        "pk": profile_id.group(1) if profile_id else None,
        "username": (
            _extract_username_from_og_url(_meta(html, "og:url")) or requested_username
        ),
        "full_name": og_title.split(" (@", 1)[0].strip() if " (@" in og_title else None,
        "biography": bio.group(1) if bio else None,
        "profile_pic_url": _meta(html, "og:image"),
    }


def _fill_missing_counts(user: dict, og_description: str) -> None:
    """Populate missing or non-numeric user counts from og:description."""
    for key, label in (
        ("follower_count", "Followers"),
        ("following_count", "Following"),
        ("all_media_count", "Posts"),
    ):
        coerced = safe_positive_int(user.get(key))
        user[key] = (
            coerced if coerced is not None else _parse_count(og_description, label)
        )


def _extract_highlights(user: dict) -> list[dict]:
    """Build normalized highlight dicts from the Relay highlights connection."""
    return [
        {
            "id": node.get("id"),
            "title": node.get("title"),
            "url": f"https://www.instagram.com/stories/highlights/{node.get('id')}/",
            "cover_url": node.get("cover_media_cropped_thumbnail_url"),
        }
        for node in _iter_connection_nodes(user, "lox_highlights_connection")
    ]


def _extract_posts(user: dict) -> list[dict]:
    """Build normalized post dicts from the Relay timeline connection."""
    posts: list[dict] = []
    for node in _iter_connection_nodes(user, "polaris_ordered_timeline_connection"):
        caption = node.get("caption")
        code = node.get("code")
        posts.append(
            {
                "id": node.get("pk"),
                "shortcode": code,
                "url": f"https://www.instagram.com/p/{code}/",
                "media_type": node.get("media_type"),
                "product_type": node.get("product_type"),
                "caption": caption.get("text") if isinstance(caption, dict) else None,
                "accessibility_caption": node.get("accessibility_caption"),
                "carousel_media_count": node.get("carousel_media_count"),
                "thumbnail_url": node.get("display_uri"),
            },
        )
    return posts


def _build_profile_payload(user: dict) -> dict:
    """Map raw Relay/meta user fields into the public profile response dict."""
    raw_bio_links = user.get("bio_links")
    bio_links = [
        {
            "title": link.get("title"),
            "url": link.get("url"),
            "link_type": link.get("link_type"),
            "is_pinned": link.get("is_pinned"),
        }
        for link in (raw_bio_links if isinstance(raw_bio_links, list) else [])
        if isinstance(link, dict)
    ]
    raw_pronouns = user.get("pronouns")
    raw_badges = user.get("account_badges")
    return {
        "id": user.get("pk"),
        "graph_api_id": user.get("id"),
        "username": user.get("username"),
        "full_name": user.get("full_name"),
        "biography": user.get("biography"),
        "pronouns": raw_pronouns if isinstance(raw_pronouns, list) else [],
        "bio_links": bio_links,
        "profile_photo_url": user.get("profile_pic_url"),
        "follower_count": user.get("follower_count"),
        "following_count": user.get("following_count"),
        "post_count": user.get("all_media_count"),
        "is_private": user.get("is_private"),
        "is_verified": user.get("is_verified"),
        "restriction": user.get("restriction"),
        "is_memorialized": user.get("is_memorialized"),
        "is_unpublished": user.get("is_unpublished"),
        "is_coppa_enforced": user.get("is_coppa_enforced"),
        "has_reels": user.get("has_any_clips"),
        "latest_story_timestamp": user.get("latest_reel_media") or None,
        "show_threads_badge": user.get("show_text_post_app_badge"),
        "account_badges": raw_badges if isinstance(raw_badges, list) else [],
        "linked_facebook": user.get("linked_fb_info"),
        "highlights": _extract_highlights(user),
        "posts": _extract_posts(user),
    }


def _parse_profile_page(
    html: str,
    *,
    requested_username: str | None = None,
) -> dict | None:
    """Parse profile data from Relay preload JSON or OpenGraph fallback tags."""
    user: dict = {}
    for block in _iter_embedded_json_dicts(html, "xig_user_by_username"):
        user.update(block)

    og_description = _meta(html, "og:description") or ""
    if not user.get("username"):
        fallback = _fallback_user_from_meta(html, og_description, requested_username)
        if fallback is None:
            return None
        user = fallback

    _fill_missing_counts(user, og_description)
    for gating in _iter_embedded_json_dicts(html, "gating"):
        restriction = gating.get("description") or gating.get("title")
        if restriction:
            user["restriction"] = str(restriction)
        break

    return _build_profile_payload(user)


def _validate_http_response(status_code: int, final_url: str) -> bool:
    """Return True when the HTTP response holds a profile page, False for 404."""
    if status_code == HTTPStatus.NOT_FOUND:
        return False
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        msg = "Instagram rate limited the profile request."
        raise InstagramProfileError(
            ERROR_RATE_LIMITED,
            msg,
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
        )
    if status_code >= HTTPStatus.BAD_REQUEST:
        msg = f"Instagram returned HTTP {status_code}."
        raise InstagramProfileError(
            ERROR_UPSTREAM,
            msg,
            status_code=HTTPStatus.BAD_GATEWAY,
        )
    if "/accounts/login" in final_url:
        msg = "Instagram redirected to the login page."
        raise InstagramProfileError(
            ERROR_LOGIN_WALL,
            msg,
            status_code=HTTPStatus.BAD_GATEWAY,
        )
    return True


def fetch_instagram_profile(
    username: str,
    *,
    proxy: ProxyConfig | None = None,
) -> dict | None:
    """Fetch and parse a public Instagram profile page without SaveAPI.

    Reads proxy configuration from ProxySetting when proxy is None.
    Returns None when the profile does not exist.
    """
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        msg = "Instagram username must be 1-30 characters of letters, digits, . or _."
        raise InstagramProfileError(
            ERROR_INVALID_USERNAME,
            msg,
            status_code=HTTPStatus.BAD_REQUEST,
        )

    logger.info("Fetching Instagram profile directly for username: %s", username)
    try:
        status_code, final_url, html = fetch_page(
            f"https://www.instagram.com/{username}/",
            headers=PROFILE_HEADERS,
            proxy=proxy,
        )
    except HttpFetchError as exc:
        raise InstagramProfileError(
            ERROR_UPSTREAM,
            str(exc),
            status_code=HTTPStatus.BAD_GATEWAY,
        ) from exc

    if not _validate_http_response(status_code, final_url):
        return None
    return _parse_profile_page(html, requested_username=username)
