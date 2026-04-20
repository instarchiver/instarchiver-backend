import logging
import uuid

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

from core.utils.openai import moderate_image_content
from core.utils.openrouter import generate_image_embedding
from instagram.misc import get_user_story_upload_location
from instagram.models.mixins import InstagramModerationMixin

logger = logging.getLogger(__name__)


class Story(InstagramModerationMixin):
    story_id = models.CharField(unique=True, max_length=50, primary_key=True)
    user = models.ForeignKey("instagram.User", on_delete=models.CASCADE)
    thumbnail_url = models.URLField(max_length=2500, blank=True)
    media_url = models.URLField(max_length=2500, blank=True)
    blur_data_url = models.TextField(blank=True)

    thumbnail = models.ImageField(
        upload_to=get_user_story_upload_location,
        blank=True,
        null=True,
    )
    media = models.FileField(
        upload_to=get_user_story_upload_location,
        blank=True,
        null=True,
    )

    thumbnail_insight = models.TextField(blank=True)
    thumbnail_insight_token_usage = models.IntegerField(default=0)

    embedding = VectorField(dimensions=1536, blank=True, null=True)
    embedding_token_usage = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    story_created_at = models.DateTimeField()

    raw_api_data = models.JSONField(blank=True, null=True)

    class Meta:
        verbose_name = "Story"
        verbose_name_plural = "Stories"

    def __str__(self):
        return f"{self.user.username} - {self.story_id}"

    def download_thumbnail(self) -> str | None:
        """
        Download thumbnail from thumbnail_url if the thumbnail field is empty.

        Returns:
            Saved file name if downloaded, None otherwise.
        """
        from django.core.files.base import ContentFile  # noqa: PLC0415

        from instagram.utils import download_file_from_url  # noqa: PLC0415

        if not (self.thumbnail_url and not self.thumbnail):
            return None
        content, extension = download_file_from_url(self.thumbnail_url)
        if content and extension:
            filename = f"{uuid.uuid4()}.{extension}"
            self.thumbnail.save(filename, ContentFile(content), save=False)
            logger.info("Downloaded thumbnail for story %s", self.story_id)
            return self.thumbnail.name
        return None

    def download_media(self) -> str | None:
        """
        Download media from media_url if the media field is empty.

        Returns:
            Saved file name if downloaded, None otherwise.
        """
        from django.core.files.base import ContentFile  # noqa: PLC0415

        from instagram.utils import download_file_from_url  # noqa: PLC0415

        if not (self.media_url and not self.media):
            return None
        content, extension = download_file_from_url(self.media_url)
        if content and extension:
            filename = f"{uuid.uuid4()}.{extension}"
            self.media.save(filename, ContentFile(content), save=False)
            logger.info("Downloaded media for story %s", self.story_id)
            return self.media.name
        return None

    def queue_thumbnail_download(self) -> None:
        """Queue a background task to download the thumbnail file."""
        from instagram.tasks import download_story_thumbnail_from_url  # noqa: PLC0415

        download_story_thumbnail_from_url.delay(self.story_id)

    def queue_media_download(self) -> None:
        """Queue a background task to download the media file."""
        from instagram.tasks import download_story_media_from_url  # noqa: PLC0415

        download_story_media_from_url.delay(self.story_id)

    def generate_blur_data_url_task(self):
        """
        Generates a blurred data URL from the media_url using a Celery task.
        This method queues the blur data URL generation as a background task.
        """
        from instagram.tasks import story_generate_blur_data_url  # noqa: PLC0415

        story_generate_blur_data_url.delay(self.story_id)

    def generate_embedding_task(self):
        """
        Generates embedding vector for the story using a Celery task.
        This method queues the embedding generation as a background task.
        """
        from instagram.tasks import generate_story_embedding  # noqa: PLC0415

        generate_story_embedding.delay(self.story_id)

    def generate_embedding(self):
        """
        Generate embedding vector for the story using OpenRouter image embeddings API.

        Returns:
            list[float]: Generated embedding vector, or None if generation fails

        Raises:
            ValueError: If thumbnail is not available
            ImproperlyConfigured: If OpenRouter settings are not configured
        """
        logger = logging.getLogger(__name__)

        if not self.thumbnail:
            msg = f"Thumbnail file does not exist for story {self.story_id}"
            raise ValueError(msg)

        try:
            embedding, token_usage = generate_image_embedding(
                "https://cdn.instarchiver.net/users/tumoutousdac/stories/8a25e9a0-954d-41d3-86ce-ef388f970e5a.jpg",
            )

            self.embedding = embedding
            self.embedding_token_usage = token_usage
            self.save(update_fields=["embedding", "embedding_token_usage"])

            logger.info(
                "Generated embedding for story %s (dimensions: %d, tokens: %d)",
                self.story_id,
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
        """
        Moderate the story content using OpenAI's content moderation API.
        """

        if not self.thumbnail:
            msg = "Thumbnail is required for content moderation"
            raise ValueError(msg)

        result = moderate_image_content(self.thumbnail.url)
        self.is_flagged = result.get("flagged", False)
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
