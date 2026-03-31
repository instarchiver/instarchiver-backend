import base64
import logging
from io import BytesIO

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField
from PIL import Image

from core.utils.openai import get_openai_client
from core.utils.openai import moderate_image_content
from instagram.misc import get_user_story_upload_location
from instagram.models.mixins import InstagramModerationMixin


class Story(InstagramModerationMixin):
    story_id = models.CharField(unique=True, max_length=50, primary_key=True)
    user = models.ForeignKey("instagram.User", on_delete=models.CASCADE)
    thumbnail_url = models.URLField(max_length=2500, blank=True)
    blur_data_url = models.TextField(blank=True)
    media_url = models.URLField(max_length=2500, blank=True)

    thumbnail = models.ImageField(
        upload_to=get_user_story_upload_location,
        blank=True,
        null=True,
    )
    thumbnail_insight = models.TextField(blank=True)
    thumbnail_insight_token_usage = models.IntegerField(default=0)
    media = models.FileField(
        upload_to=get_user_story_upload_location,
        blank=True,
        null=True,
    )
    raw_api_data = models.JSONField(blank=True, null=True)

    embedding = VectorField(dimensions=1536, blank=True, null=True)
    embedding_token_usage = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    story_created_at = models.DateTimeField()

    class Meta:
        verbose_name = "Story"
        verbose_name_plural = "Stories"

    def __str__(self):
        return f"{self.user.username} - {self.story_id}"

    def generate_blur_data_url_task(self):
        """
        Generates a blurred data URL from the media_url using a Celery task.
        This method queues the blur data URL generation as a background task.
        """
        from instagram.tasks import story_generate_blur_data_url  # noqa: PLC0415

        story_generate_blur_data_url.delay(self.story_id)

    def generate_thumbnail_insight_task(self):
        """
        Generates AI-powered thumbnail insight using a Celery task.
        This method queues the thumbnail insight generation as a background task.
        """
        from instagram.tasks import generate_story_thumbnail_insight  # noqa: PLC0415

        generate_story_thumbnail_insight.delay(self.story_id)

    def generate_embedding_task(self):
        """
        Generates embedding vector for the story using a Celery task.
        This method queues the embedding generation as a background task.
        """
        from instagram.tasks import generate_story_embedding  # noqa: PLC0415

        generate_story_embedding.delay(self.story_id)

    def generate_thumbnail_insight(self):
        """
        Generate AI-powered insight for the story thumbnail using OpenAI Vision API.

        This method encodes the thumbnail image and sends it to OpenAI's GPT-4 Vision
        model to generate a descriptive insight about the story content.

        Returns:
            str: Generated insight text, or empty string if generation fails

        Raises:
            ValueError: If thumbnail file doesn't exist
            ImproperlyConfigured: If OpenAI settings are not configured
        """
        logger = logging.getLogger(__name__)

        # Check if thumbnail exists
        if not self.thumbnail:
            msg = f"Thumbnail file does not exist for story {self.story_id}"
            raise ValueError(msg)

        try:
            # Load and optimize image to reduce token usage
            # Use .open() instead of .path for S3 compatibility
            with self.thumbnail.open("rb") as image_file:
                # Open image with PIL
                image = Image.open(image_file)

                # Resize to 50% to reduce token usage
                # Calculate new dimensions (50% of original)
                new_width = image.width // 2
                new_height = image.height // 2

                # Resize image
                resized_image = image.resize(
                    (new_width, new_height),
                    Image.Resampling.LANCZOS,
                )

                # Convert to RGB if necessary (for JPEG compatibility)
                if resized_image.mode in ("RGBA", "P", "LA"):
                    resized_image = resized_image.convert("RGB")

                # Compress and encode to base64
                buffer = BytesIO()
                resized_image.save(buffer, format="JPEG", quality=60, optimize=True)
                base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # Get OpenAI client and model
            client = get_openai_client()
            model_name = "gpt-5-mini"

            # Create chat completion with vision
            prompt_text = (
                "Analyze this image and create detailed description about the image."
                "The description should be detail as possible for text embedding data."
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt_text,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    },
                ],
            )

            # Extract and save the insight
            insight = response.choices[0].message.content.strip()
            self.thumbnail_insight = insight
            self.thumbnail_insight_token_usage = response.usage.total_tokens
            self.save(
                update_fields=["thumbnail_insight", "thumbnail_insight_token_usage"],
            )

        except FileNotFoundError:
            logger.exception("Thumbnail file not found for story %s", self.story_id)
            raise
        except Exception:
            logger.exception(
                "Failed to generate thumbnail insight for story %s",
                self.story_id,
            )
            return ""
        else:
            logger.info("Generated thumbnail insight for story %s", self.story_id)

    def generate_embedding(self):
        """
        Generate embedding vector for the story using OpenAI embeddings API.

        This method uses the story's thumbnail_insight to create a text representation,
        then generates a 1536-dimensional embedding vector using OpenAI's
        text-embedding-3-small model.

        Note: Embedding generation requires thumbnail_insight to be available,
        as it provides AI-generated visual context essential for accurate embeddings.

        Returns:
            list[float]: Generated embedding vector, or None if generation fails

        Raises:
            ValueError: If thumbnail_insight is empty
            ImproperlyConfigured: If OpenAI settings are not configured
        """
        logger = logging.getLogger(__name__)

        # Check if thumbnail_insight is available
        if not self.thumbnail_insight:
            msg = f"Thumbnail insight is not available for story {self.story_id}"
            raise ValueError(msg)

        # Use thumbnail_insight as the embedding input
        embedding_text = self.thumbnail_insight

        try:
            from core.utils.openai import generate_text_embedding  # noqa: PLC0415

            # Generate embedding
            embedding, token_usage = generate_text_embedding(embedding_text)

            # Save to model
            self.embedding = embedding
            self.embedding_token_usage = token_usage
            self.save(update_fields=["embedding", "embedding_token_usage"])

            logger.info(
                "Generated embedding for story %s (text length: %d, dimensions: %d, tokens: %d)",  # noqa: E501
                self.story_id,
                len(embedding_text),
                len(embedding),
                token_usage,
            )

            return embedding  # noqa: TRY300

        except ValueError:
            logger.exception(
                "ValueError generating embedding for story %s",
                self.story_id,
            )
            raise
        except Exception:
            logger.exception("Failed to generate embedding for story %s", self.story_id)
            return None

    def moderate_content(self):
        if not self.thumbnail:
            msg = "Thumbnail is required for content moderation"
            raise ValueError(msg)

        result = moderate_image_content(self.thumbnail.url)
        self.is_flagged = result.get("is_flagged", False)
        self.moderation_result = result
        self.moderated_at = timezone.localtime()
        self.save(update_fields=["is_flagged", "moderation_result", "moderated_at"])


class UserUpdateStoryLog(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey("instagram.User", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Update Story Log"
        verbose_name_plural = "User Update Story Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Story Update for {self.user.username} - {self.status}"
