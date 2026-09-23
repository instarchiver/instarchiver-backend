import base64
import logging
from io import BytesIO
from urllib.parse import urlparse

import av
import requests
from PIL import Image as PILImage
from rest_framework import status

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


def generate_blur_data_url_from_image_url(
    image_url: str,
    resize_percentage: float = 0.02,
) -> str:
    """
    Generates a blurred data URL from an image URL.

    This function retrieves an image from the provided URL,
    resizes it to a specified percentage of its original dimensions,
    converts it to a base64 string, and returns it.

    Args:
        image_url (str): The URL of the image to process
        resize_percentage (float): Percentage to resize (default: 0.02 = 2%)

    Returns:
        str: Base64 encoded string of the resized image

    Raises:
        requests.exceptions.RequestException: If there's an error fetching the image
        IOError: If there's an error processing the image
    """
    logger.info("Generating blur data URL from image URL: %s", image_url)

    # Fetch the image from URL using requests
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()  # Raise exception for HTTP errors

    # Open the image from the response content
    img = PILImage.open(BytesIO(response.content))

    # Calculate new dimensions
    width, height = img.size
    new_width = int(width * resize_percentage)
    new_height = int(height * resize_percentage)

    # Resize the image
    resized_img = img.resize((new_width, new_height))

    # Convert to base64
    buffer = BytesIO()
    img_format = img.format or "JPEG"
    resized_img.save(buffer, format=img_format)
    base64_string = base64.b64encode(buffer.getvalue()).decode("utf-8")

    logger.info("Successfully generated blur data URL")
    return base64_string


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
