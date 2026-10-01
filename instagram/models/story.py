import logging
import uuid

from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

from core.utils.openai import moderate_image_content
from core.utils.openrouter import generate_image_embedding
from instagram.misc import get_user_story_upload_location
from instagram.models.mixins import InstagramModerationMixin
from instagram.models.mixins import ViewCountMixin
from instagram.utils import download_file_from_url
from instagram.utils import extract_video_frame

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}


def is_video_filename(name):
    """Check whether a file name has a video extension.

    Args:
        name (str or None): file name to check

    Returns:
        bool: True if the extension is in VIDEO_EXTENSIONS
    """
    return bool(name) and name.rsplit(".", 1)[-1].lower() in VIDEO_EXTENSIONS


class Story(InstagramModerationMixin, ViewCountMixin):
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

    def _download(self, field_name, url):
        """Download url into the given file field if that field is empty.

        The file is attached to the instance without saving the row.

        Args:
            field_name (str): "thumbnail" or "media"
            url (str): source URL, may be empty

        Returns:
            str or None: saved file name, or None if nothing was downloaded
        """
        field = getattr(self, field_name)
        if not url or field:
            return None
        content, extension = download_file_from_url(url)
        if not (content and extension):
            return None
        field.save(f"{uuid.uuid4()}.{extension}", ContentFile(content), save=False)
        logger.info("Downloaded %s for story %s", field_name, self.story_id)
        return field.name

    def download_thumbnail(self):
        """Download thumbnail_url into thumbnail if it is empty.

        Returns:
            str or None: saved file name, or None if nothing was downloaded
        """
        return self._download("thumbnail", self.thumbnail_url)

    def download_media(self):
        """Download media_url into media if it is empty.

        Returns:
            str or None: saved file name, or None if nothing was downloaded
        """
        return self._download("media", self.media_url)

    def generate_thumbnail_from_media(self):
        """Build a JPEG thumbnail from a frame of the stored video.

        Video stories from SaveAPI come without a thumbnail. The frame is read
        from storage, so it works after the Instagram CDN URL expires.

        Returns:
            str or None: saved file name, or None if nothing was generated
        """
        if self.thumbnail or not (self.media and is_video_filename(self.media.name)):
            return None

        with self.media.open("rb") as media_file:
            content = extract_video_frame(media_file)
        if not content:
            return None

        self.thumbnail.save(f"{uuid.uuid4()}.jpg", ContentFile(content), save=False)
        logger.info("Generated thumbnail from media for story %s", self.story_id)
        return self.thumbnail.name

    def generate_embedding(self):
        """Generate and save an embedding of the thumbnail through OpenRouter.

        Returns:
            list[float]: the embedding vector

        Raises:
            ValueError: if the story has no thumbnail
            ImproperlyConfigured: if OpenRouter is not configured
            requests.RequestException: if the OpenRouter call fails
        """
        if not self.thumbnail:
            msg = f"Thumbnail file does not exist for story {self.story_id}"
            raise ValueError(msg)

        embedding, token_usage = generate_image_embedding(self.thumbnail.url)
        self.embedding = embedding
        self.embedding_token_usage = token_usage
        self.save(update_fields=["embedding", "embedding_token_usage"])
        logger.info(
            "Generated embedding for story %s (dimensions: %d, tokens: %d)",
            self.story_id,
            len(embedding),
            token_usage,
        )
        return embedding

    def moderate_content(self):
        """Run the thumbnail through OpenAI moderation and save the result.

        Raises:
            ValueError: if the story has no thumbnail
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
