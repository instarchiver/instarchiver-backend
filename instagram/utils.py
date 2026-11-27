import base64
import logging
import re
from io import BytesIO
from urllib.parse import urlparse

import av
import requests
from PIL import Image as PILImage
from rest_framework import status

from core.utils.openrouter import classify
from instagram.constants import ALLOWED_INSTAGRAM_HOSTS
from instagram.constants import INSTAGRAM_SHORTCODE_ALPHABET
from instagram.constants import INSTAGRAM_URL_CATEGORIES
from instagram.constants import INSTAGRAM_URL_QUESTION
from instagram.constants import INSTAGRAM_USERNAME_RE
from instagram.constants import MAX_STANDARD_SHORTCODE_LEN
from instagram.constants import RESERVED_INSTAGRAM_SEGMENTS

logger = logging.getLogger(__name__)


def download_file_from_url(url, timeout=30):
    """Download file from URL and return content with extension."""

    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code == status.HTTP_200_OK:
            # Extract file extension from URL
            parsed_url = urlparse(url)
            path = parsed_url.path
            if "." in path:
                extension = path.split(".")[-1].lower()
            else:
                # Try to determine from content type
                content_type = response.headers.get("content-type", "")
                if "image" in content_type:
                    extension = "jpg"
                elif "video" in content_type:
                    extension = "mp4"
                else:
                    extension = "bin"

            return response.content, extension
        logger.warning(
            "Failed to download file from %s: HTTP %s",
            url,
            response.status_code,
        )
        return None, None  # noqa: TRY300
    except Exception as e:
        logger.exception("Error downloading file from %s: %s", url, str(e))  # noqa: TRY401
        return None, None


def generate_blur_data_url_from_image(img, resize_percentage=0.02):
    """Shrink an opened image and return it as a base64 JPEG string.

    The output is always JPEG, because the frontend labels every blur as
    image/jpeg. Each side is at least 1px.

    Args:
        img (PIL.Image.Image): the image to shrink
        resize_percentage (float): share of the original size to keep

    Returns:
        str: base64 encoded JPEG
    """
    width, height = img.size
    new_size = (
        max(1, int(width * resize_percentage)),
        max(1, int(height * resize_percentage)),
    )
    buffer = BytesIO()
    img.convert("RGB").resize(new_size).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# EXIF Orientation values that turn the picture by 90 degrees.
ROTATED_EXIF_ORIENTATIONS = {5, 6, 7, 8}


def get_media_size(content):
    """Return the width and height of image or video bytes.

    Images are tried first, so AVIF/HEIC (which also start with an ftyp box)
    are not read as video. An image turned by EXIF reports the size it is
    shown at. Videos are read from the stream header without decoding.

    shortcut: video rotation metadata is ignored, so a rotated phone video
    reports its stored size; read the display matrix if that matters.

    Args:
        content (bytes): the downloaded file

    Returns:
        tuple: (width, height) as ints, or (None, None) if unreadable
    """
    try:
        with PILImage.open(BytesIO(content)) as img:
            width, height = img.size
            if img.getexif().get(0x0112) in ROTATED_EXIF_ORIENTATIONS:
                width, height = height, width
            return width, height
    except (OSError, ValueError):
        pass

    try:
        with av.open(BytesIO(content)) as container:
            codec = container.streams.video[0].codec_context
            return codec.width, codec.height
    except (av.error.FFmpegError, IndexError, ValueError):
        logger.warning("Could not read the size of the downloaded media")
        return None, None


def extract_video_frame(file_obj, at_seconds: float = 1.0) -> bytes | None:
    """Grab one frame from a video and return it as JPEG bytes.

    Decodes frames until it reaches ``at_seconds``. Videos shorter than that
    fall back to the last decoded frame.

    Args:
        file_obj: Seekable binary file-like object holding the video
        at_seconds: Position of the frame to capture, in seconds

    Returns:
        JPEG bytes, or None if no frame could be decoded
    """
    try:
        with av.open(file_obj) as container:
            frame = None
            for frame in container.decode(video=0):
                if frame.time is not None and frame.time >= at_seconds:
                    break

            if frame is None:
                logger.warning("No video frames found to extract")
                return None

            buffer = BytesIO()
            frame.to_image().save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception as e:
        logger.exception("Error extracting frame from video: %s", str(e))  # noqa: TRY401
        return None


def categorize_instagram_url(url: str) -> str:
    """Tell whether an Instagram URL is a story, a post, or unknown."""
    return classify(
        state=url,
        question=INSTAGRAM_URL_QUESTION,
        categories=INSTAGRAM_URL_CATEGORIES,
    )


_POST_PATH_RE = re.compile(r"\A/(?:p|reel|reels|tv)/(?P<code>[A-Za-z0-9_-]+)/?\Z")
_USER_POST_PATH_RE = re.compile(
    r"\A/(?P<username>[^/]+)/(?:p|reel|reels|tv)/(?P<code>[A-Za-z0-9_-]+)/?\Z",
)
_SHARE_PATH_RE = re.compile(
    r"\A/share/(?:(?P<kind>p|reel)/)?(?P<code>[A-Za-z0-9_-]+)/?\Z",
)


def validate_instagram_username(raw: object) -> str | None:
    """Return a normalized Instagram username, or None if invalid."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if candidate.startswith("@"):
        candidate = candidate[1:]
    if (
        not candidate
        or ".." in candidate
        or candidate.lower() in RESERVED_INSTAGRAM_SEGMENTS
        or not INSTAGRAM_USERNAME_RE.fullmatch(candidate)
    ):
        return None
    return candidate.lower()


def _is_valid_instagram_url_netloc(parsed) -> bool:
    """Return True if parsed URL uses HTTP(S) on an Instagram host."""
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.hostname.lower() in ALLOWED_INSTAGRAM_HOSTS
        and not parsed.username
        and not parsed.password
        and port is None
    )


def normalize_instagram_post_url(url: str) -> tuple[str, str | None]:
    """Validate and normalize an Instagram post or reel URL.

    Returns:
        tuple: (canonical_url, shortcode_or_none)

    Raises:
        TypeError: if url is not a string
        ValueError: if the URL is not a supported Instagram post URL
    """
    if not isinstance(url, str):
        msg = "URL must be a string."
        raise TypeError(msg)

    cleaned = url.strip()
    if not cleaned or any(ch in cleaned for ch in ("\r", "\n", "\t")):
        msg = "Enter a valid Instagram post or reel URL."
        raise ValueError(msg)

    parsed = urlparse(cleaned)
    if not _is_valid_instagram_url_netloc(parsed):
        msg = "Enter a valid Instagram post or reel URL."
        raise ValueError(msg)

    path = parsed.path
    clean_path = path if path.endswith("/") else f"{path}/"
    canonical_url = f"https://www.instagram.com{clean_path}"

    match = _POST_PATH_RE.fullmatch(path)
    if match:
        return canonical_url, match.group("code")

    match = _SHARE_PATH_RE.fullmatch(path)
    if match:
        if (
            match.group("kind") is None
            and match.group("code").lower() in RESERVED_INSTAGRAM_SEGMENTS
        ):
            msg = "Enter a valid Instagram post or reel URL."
            raise ValueError(msg)
        return canonical_url, None

    match = _USER_POST_PATH_RE.fullmatch(path)
    if match:
        username = validate_instagram_username(match.group("username"))
        if username is None:
            msg = "Enter a valid Instagram post or reel URL."
            raise ValueError(msg)
        return canonical_url, match.group("code")

    msg = "Only Instagram post and reel URLs are supported."
    raise ValueError(msg)


def shortcode_to_media_id(shortcode: str | None) -> str | None:
    """Decode an Instagram post shortcode into its numeric media PK."""
    if (
        not isinstance(shortcode, str)
        or not 1 <= len(shortcode) <= MAX_STANDARD_SHORTCODE_LEN
    ):
        return None

    media_id = 0
    for char in shortcode:
        index = INSTAGRAM_SHORTCODE_ALPHABET.find(char)
        if index == -1:
            return None
        media_id = media_id * 64 + index

    return str(media_id) if media_id > 0 else None
