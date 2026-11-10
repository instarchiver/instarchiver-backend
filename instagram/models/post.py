import logging
import uuid

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils import timezone
from pgvector.django import VectorField
from simple_history.models import HistoricalRecords

from instagram.misc import get_post_media_upload_location
from instagram.models.mixins import InstagramModerationMixin
from instagram.models.mixins import ViewCountMixin
from instagram.models.user import User
from instagram.utils import download_file_from_url

logger = logging.getLogger(__name__)


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

    def download_thumbnail(self):
        """Download thumbnail_url into thumbnail and save the file name.

        Unlike Story.download_thumbnail, this writes to the database. The name
        is stored with a queryset update, so post_save does not fire and no
        history row is added. The update only applies while the row has no
        thumbnail. If another worker stored one first, the new file is
        deleted.

        The upload path reads user.username, so load user before calling.

        Returns:
            str or None: saved file name, or None if nothing was saved
        """
        if not self.thumbnail_url or self.thumbnail:
            return None
        content, extension = download_file_from_url(self.thumbnail_url)
        if not (content and extension):
            return None

        self.thumbnail.save(
            f"{uuid.uuid4()}.{extension}",
            ContentFile(content),
            save=False,
        )
        updated = (
            Post.objects.filter(pk=self.pk)
            .filter(Q(thumbnail="") | Q(thumbnail__isnull=True))
            .update(thumbnail=self.thumbnail.name)
        )
        if not updated:
            self.thumbnail.delete(save=False)
            return None
        logger.info("Downloaded thumbnail for post %s", self.pk)
        return self.thumbnail.name


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
