import logging

import requests
from django.core.exceptions import ImproperlyConfigured

from settings.models import OpenRouterSetting

logger = logging.getLogger(__name__)

CLASSIFICATION_URL = "https://openrouter.ai/api/alpha/decisions"
CLASSIFICATION_MODEL = "typesafe/jev-1.13"


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
                "HTTP-Referer": "https://instarchiver.net",
                "X-OpenRouter-Title": "Instarchiver",
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


def classify(
    state: str,
    question: str,
    categories: list[str],
    model: str = CLASSIFICATION_MODEL,
) -> str:
    """Pick the category that best fits the state, using an OpenRouter score question.

    Args:
        state: The input to classify, for example a URL
        question: What the model should decide about the state
        categories: The labels to choose from
        model: OpenRouter model id

    Returns:
        The category with the highest probability

    Raises:
        ImproperlyConfigured: If the API key is missing
        Exception: If the API request fails or the response has no answer
    """
    api_key = get_api_key()

    try:
        response = requests.post(
            CLASSIFICATION_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://instarchiver.net",
                "X-OpenRouter-Title": "Instarchiver",
            },
            json={
                "model": model,
                "state": state,
                "questions": {
                    "classification": {
                        "type": "score",
                        "instructions": question,
                        "criteria": categories,
                    },
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        answer = response.json()["answers"]["classification"]

        probabilities = answer["probabilities"]
        best = max(probabilities, key=probabilities.get)
        category = answer["legend"][best]

        logger.info("Classified %s as %s", state, category)

        return category  # noqa: TRY300

    except Exception:
        logger.exception("Failed to classify %s", state)
        raise
