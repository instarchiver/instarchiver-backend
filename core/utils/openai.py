import logging

import openai
from django.core.exceptions import ImproperlyConfigured

from settings.models import OpenAISetting

logger = logging.getLogger(__name__)


def get_api_key() -> str:
    """Retrieve OpenAI API key from settings."""
    setting = OpenAISetting.get_solo()
    if not setting.api_key:
        msg = "OpenAI API key is not configured in settings"
        raise ImproperlyConfigured(msg)
    return setting.api_key


def get_model_name() -> str:
    """Retrieve OpenAI model name from settings."""
    setting = OpenAISetting.get_solo()
    return setting.model_name


def get_openai_client(model_name: str | None = None) -> openai.OpenAI:
    """Initialize and return OpenAI client with configured settings.

    Args:
        model_name: Override the default model name from settings
    """
    api_key = get_api_key()
    if model_name is None:
        model_name = get_model_name()
    return openai.OpenAI(api_key=api_key)


def validate_settings() -> bool:
    """Validate OpenAI settings are properly configured."""
    try:
        setting = OpenAISetting.get_solo()
        return bool(setting.api_key and setting.api_key.strip())
    except (AttributeError, ImportError):
        return False


def check_connection() -> bool:
    """Check if OpenAI API connection is working."""
    try:
        client = get_openai_client()
        client.models.list()
    except Exception as e:
        logger.exception("Failed to connect to OpenAI API: %s", e)  # noqa: TRY401
        return False
    else:
        return True


def generate_text_embedding(text: str) -> tuple[list[float], int]:
    """Generate embedding vector for the given text using OpenAI embeddings API.

    Args:
        text: Input text to generate embedding for

    Returns:
        Tuple of (embedding vector, token usage):
        - embedding: List of floats representing the 1536-dimensional embedding vector
        - token_usage: Total tokens used for this API call

    Raises:
        ImproperlyConfigured: If OpenAI settings are not configured
        ValueError: If text is empty
        Exception: If the API request fails
    """
    if not text or not text.strip():
        msg = "Text cannot be empty for embedding generation"
        raise ValueError(msg)

    try:
        client = get_openai_client()
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )

        embedding = response.data[0].embedding
        token_usage = response.usage.total_tokens

        logger.info(
            "Generated embedding with %d dimensions for text of length %d (tokens: %d)",
            len(embedding),
            len(text),
            token_usage,
        )

        return embedding, token_usage  # noqa: TRY300

    except Exception:
        logger.exception("Failed to generate embedding for text")
        raise


def moderate_image_content(image_url: str) -> dict:
    """Moderate image content using OpenAI's moderation API.

    Args:
        image_url: URL of the image to be moderated

    Returns:
        Moderation result as a dictionary containing flagged status and categories

    Raises:
        ImproperlyConfigured: If OpenAI settings are not configured
        ValueError: If image_url is empty or invalid
        Exception: If the API request fails
    """
    if not image_url or not image_url.strip():
        msg = "Image URL cannot be empty for content moderation"
        raise ValueError(msg)

    try:
        client = get_openai_client()
        response = client.moderations.create(
            model="omni-moderation-latest",
            input=[{"type": "image_url", "image_url": {"url": image_url}}],
        )

        result = response.results[0]

        return result.dict()  # Convert OpenAI response object to a regular dictionary

    except Exception:
        logger.exception("Failed to moderate image content for URL %s", image_url)
        raise
