import base64
import logging
from io import BytesIO
from urllib.parse import urlparse

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
