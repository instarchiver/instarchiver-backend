import logging

import requests
from django.core.exceptions import ImproperlyConfigured

from settings.models import OpenRouterSetting

logger = logging.getLogger(__name__)


def get_api_key() -> str:
    setting = OpenRouterSetting.get_solo()
    if not setting.embedding_api_key:
        msg = "OpenRouter API key is not configured in settings"
        raise ImproperlyConfigured(msg)
    return setting.embedding_api_key


def generate_image_embedding(image_url: str) -> tuple[list[float], int]:
    """Generate embedding vector for an image using OpenRouter embeddings API.

    Args:
        image_url: URL of the image to embed

    Returns:
        Tuple of (embedding vector, token_usage)

    Raises:
        ImproperlyConfigured: If OpenRouter settings are not configured
        ValueError: If image_url is empty
        Exception: If the API request fails
    """
    if not image_url or not image_url.strip():
        msg = "Image URL cannot be empty for image embedding generation"
        raise ValueError(msg)

    setting = OpenRouterSetting.get_solo()
    api_key = get_api_key()
    base_url = setting.embedding_base_url
    model = setting.image_embedding_model

    try:
        response = requests.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": [
                    {
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    },
                ],
                "encoding_format": "float",
                "dimensions": 1536,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        embedding = data["data"][0]["embedding"]
        token_usage = data.get("usage", {}).get("total_tokens", 0)

        logger.info(
            "Generated image embedding with %d dimensions (tokens: %d)",
            len(embedding),
            token_usage,
        )

        return embedding, token_usage  # noqa: TRY300

    except Exception:
        logger.exception("Failed to generate image embedding for URL %s", image_url)
        raise
