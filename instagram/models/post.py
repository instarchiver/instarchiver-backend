import logging
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils import timezone
from pgvector.django import VectorField
from PIL import Image as PILImage
from PIL import ImageOps
from simple_history.models import HistoricalRecords

from instagram.misc import get_post_media_upload_location
from instagram.models.mixins import InstagramModerationMixin
from instagram.models.mixins import ViewCountMixin
from instagram.models.story import is_video_filename
from instagram.models.user import User
from instagram.utils import download_file_from_url
from instagram.utils import extract_video_frame
from instagram.utils import generate_blur_data_url_from_image

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
        deleted. When thumbnail_url points to a video, one frame is stored
        as a JPEG instead of the video.

        The upload path reads user.username, so load user before calling.

        Returns:
            str or None: saved file name, or None if nothing was saved
        """
        if not self.thumbnail_url or self.thumbnail:
            return None
        content, extension = download_file_from_url(self.thumbnail_url)
        if not (content and extension):
            return None

        # ftyp is the MP4/MOV header, for URLs without a video extension.
        if is_video_filename(f"thumbnail.{extension}") or content[4:8] == b"ftyp":
            content, extension = extract_video_frame(BytesIO(content)), "jpg"
            if not content:
                logger.warning("No frame cut from the video of post %s", self.pk)
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

    def process_thumbnail(self):
        """Fill blur_data_url, width and height from the stored thumbnail.

        The file is read from storage once and the EXIF orientation is
        applied, so the size matches what a browser shows. The values are
        saved with a queryset update, so post_save does not fire and no
        history row is added. Image and storage errors are raised.

        Returns:
            bool: True if the values were saved, False if there is no
            thumbnail
        """
        if not self.thumbnail:
            return False

        with self.thumbnail.open("rb") as thumbnail_file:
            img = ImageOps.exif_transpose(PILImage.open(thumbnail_file))
            self.width, self.height = img.size
            self.blur_data_url = generate_blur_data_url_from_image(img)

        Post.objects.filter(pk=self.pk).update(
            blur_data_url=self.blur_data_url,
            width=self.width,
            height=self.height,
        )
        logger.info("Processed thumbnail for post %s", self.pk)
        return True


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
