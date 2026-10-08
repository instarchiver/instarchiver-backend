import logging

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField
from simple_history.models import HistoricalRecords

from core.utils.openai import moderate_image_content
from core.utils.openrouter import generate_image_embedding
from instagram.misc import get_post_media_upload_location
from instagram.models.mixins import InstagramModerationMixin
from instagram.models.mixins import ViewCountMixin
from instagram.models.user import User


class Post(InstagramModerationMixin, ViewCountMixin):
    POST_VARIANT_NORMAL = "normal"
    POST_VARIANT_CAROUSEL = "carousel"
    POST_VARIANT_VIDEO = "video"

    POST_VARIANTS = (
        (POST_VARIANT_NORMAL, "Normal"),
        (POST_VARIANT_CAROUSEL, "Carousel"),
        (POST_VARIANT_VIDEO, "Video"),
    )

    id = models.CharField(max_length=50, primary_key=True, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    variant = models.CharField(
        max_length=15,
        choices=POST_VARIANTS,
        default=POST_VARIANT_NORMAL,
    )
    caption = models.TextField(blank=True)
    thumbnail_url = models.URLField(max_length=2500)
    thumbnail = models.ImageField(
        upload_to=get_post_media_upload_location,
        blank=True,
        null=True,
    )
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    blur_data_url = models.TextField(blank=True)
    raw_data = models.JSONField(blank=True, null=True)
    post_created_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    embedding = VectorField(dimensions=1536, blank=True, null=True)
    embedding_token_usage = models.IntegerField(default=0)

    history = HistoricalRecords()

    def __str__(self):
        return f"{self.user.username} - {self.id}"

    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    def generate_blur_data_url_task(self):
        """
        Generates a blurred data URL from the thumbnail_url using a Celery task.
        This method queues the blur data URL generation as a background task.
        """
        from instagram.tasks import post_generate_blur_data_url  # noqa: PLC0415

        post_generate_blur_data_url.delay(self.id)

    def generate_embedding_task(self):
        """
        Generates embedding vector for the post using a Celery task.
        This method queues the embedding generation as a background task.
        """
        from instagram.tasks import generate_post_embedding  # noqa: PLC0415

        generate_post_embedding.delay(self.id)

    def generate_embedding(self):
        """
        Generate embedding vector for the post using OpenRouter image embeddings API.

        Returns:
            list[float]: Generated embedding vector, or None if generation fails

        Raises:
            ValueError: If thumbnail is not available
            ImproperlyConfigured: If OpenRouter settings are not configured
        """
        logger = logging.getLogger(__name__)

        if not self.thumbnail:
            msg = f"Thumbnail file does not exist for post {self.id}"
            raise ValueError(msg)

        try:
            embedding, token_usage = generate_image_embedding(self.thumbnail.url)

            self.embedding = embedding
            self.embedding_token_usage = token_usage
            self.save(update_fields=["embedding", "embedding_token_usage"])

            logger.info(
                "Generated embedding for post %s (dimensions: %d, tokens: %d)",
                self.id,
                len(embedding),
                token_usage,
            )

            return embedding  # noqa: TRY300

        except ValueError:
            logger.exception("ValueError generating embedding for post %s", self.id)
            raise
        except Exception:
            logger.exception("Failed to generate embedding for post %s", self.id)
            return None

    def moderate_content(self):
        """
        Moderate the post content using OpenAI's content moderation API.
        """
        if not self.thumbnail:
            msg = "Thumbnail is required for content moderation"
            raise ValueError(msg)

        result = moderate_image_content(self.thumbnail.url)
        self.is_flagged = result.get("flagged", False)
        self.moderation_result = result
        self.moderated_at = timezone.localtime()
        self.save(update_fields=["is_flagged", "moderation_result", "moderated_at"])

    def moderate_content_task(self):
        """
        Queues post content moderation as a background task.
        """
        from instagram.tasks import moderate_post_content  # noqa: PLC0415

        moderate_post_content.delay(self.id)


class PostMedia(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    reference = models.CharField(max_length=50, default="")

    thumbnail_url = models.URLField(max_length=2500)
    media_url = models.URLField(max_length=2500)
    blur_data_url = models.TextField(blank=True)

    thumbnail = models.ImageField(
        upload_to=get_post_media_upload_location,
        blank=True,
        null=True,
    )
    media = models.FileField(
        upload_to=get_post_media_upload_location,
        blank=True,
        null=True,
    )
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("post", "reference")

    def __str__(self):
        return f"{self.post.user.username} - {self.post.id}"

    def generate_blur_data_url_task(self):
        """
        Generates a blurred data URL from the thumbnail_url using a Celery task.
        This method queues the blur data URL generation as a background task.
        """
        from instagram.tasks import post_media_generate_blur_data_url  # noqa: PLC0415

        post_media_generate_blur_data_url.delay(self.id)
