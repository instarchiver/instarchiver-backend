import json
import logging

from django.core.exceptions import ValidationError
from django.db import models
from solo.models import SingletonModel

logger = logging.getLogger(__name__)


class OpenAISetting(SingletonModel):
    api_key = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="OpenAI API Key",
    )
    model_name = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text="OpenAI Model Name",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "OpenAI Settings"

    class Meta:
        verbose_name = "OpenAI Setting"


class CoreAPISetting(SingletonModel):
    api_url = models.URLField(
        max_length=255,
        default="",
        blank=True,
        help_text="Core API URL",
    )
    api_token = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="Core API Token",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Core API Settings"

    class Meta:
        verbose_name = "Core API Setting"


class FirebaseAdminSetting(SingletonModel):
    service_account_file = models.FileField(
        upload_to="firebase/",
        blank=True,
        null=True,
        help_text="Firebase Admin SDK Service Account JSON file",
    )
    service_account_json = models.TextField(
        blank=True,
        default="",
        help_text="Firebase Admin SDK Service Account JSON content (alternative to file upload for production)",  # noqa: E501
    )
    project_id = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="Firebase Project ID (optional, usually in service account file)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Override save to auto-sync JSON field from uploaded file."""
        if self.service_account_file:
            try:
                # Read file content and populate JSON field
                file_content = self.service_account_file.read()
                if isinstance(file_content, bytes):
                    file_content = file_content.decode("utf-8")

                # Validate JSON and store it
                json.loads(file_content)  # Validates JSON format
                self.service_account_json = file_content

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                msg = "Invalid Firebase service account JSON file"
                raise ValidationError(msg) from e
            except Exception as e:
                msg = "Could not read Firebase service account file"
                raise ValidationError(msg) from e

        super().save(*args, **kwargs)

    def __str__(self):
        return "Firebase Admin Settings"

    class Meta:
        verbose_name = "Firebase Admin Setting"


class OpenRouterSetting(SingletonModel):
    embedding_api_key = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="OpenRouter API Key for embeddings",
    )
    embedding_base_url = models.URLField(
        max_length=255,
        default="https://openrouter.ai/api/v1/embeddings",
        help_text="OpenRouter Embeddings endpoint URL",
    )
    image_embedding_model = models.CharField(
        max_length=100,
        default="nvidia/llama-nemotron-embed-vl-1b-v2",
        blank=True,
        help_text="Model for image embeddings",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "OpenRouter Settings"

    class Meta:
        verbose_name = "OpenRouter Setting"


class StripeSetting(SingletonModel):
    api_key = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="Stripe API Key",
    )
    webhook_secret = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="Stripe Webhook Secret",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Stripe Settings"

    class Meta:
        verbose_name = "Stripe Setting"
