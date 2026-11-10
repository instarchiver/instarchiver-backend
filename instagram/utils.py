import base64
import logging
from io import BytesIO
from urllib.parse import urlparse

import av
import requests
from PIL import Image as PILImage
from rest_framework import status

from core.utils.openrouter import classify
from instagram.constants import INSTAGRAM_URL_CATEGORIES
from instagram.constants import INSTAGRAM_URL_QUESTION

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
