import logging
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils import timezone
from pgvector.django import VectorField
from PIL import Image as PILImage
from PIL import ImageOps
from simple_history.models import HistoricalRecords

from core.utils.openrouter import generate_image_embedding
from instagram.misc import get_post_media_upload_location
from instagram.models.mixins import InstagramModerationMixin
from instagram.models.mixins import ViewCountMixin
from instagram.models.story import is_video_filename
from instagram.models.user import User
from instagram.utils import download_file_from_url
from instagram.utils import extract_video_frame
from instagram.utils import generate_blur_data_url_from_image
from instagram.utils import get_media_size

logger = logging.getLogger(__name__)


# Posts whose stored thumbnail still needs a blur placeholder or a size.
NEEDS_THUMBNAIL_PROCESSING = Q(thumbnail__gt="") & (
    Q(blur_data_url="") | Q(width__isnull=True) | Q(height__isnull=True)
)

# Posts that can get an embedding. Old thumbnails stored as video files are
# skipped, because OpenRouter rejects them on every run.
NEEDS_EMBEDDING = Q(embedding__isnull=True, thumbnail__gt="") & ~Q(
    thumbnail__iregex=r"\.(mp4|mov|webm)$",
)

# Posts whose raw_data has media to turn into PostMedia rows. Checking the
# first item's url skips posts with empty or broken medias, which would
# otherwise be queued again on every run.
NEEDS_POST_MEDIA = Q(
    postmedia__isnull=True,
    raw_data__medias__0__url__isnull=False,
) & ~Q(
    raw_data__medias__0__url="",
)

# PostMedia rows whose stored media file has no thumbnail yet.
NEEDS_MEDIA_THUMBNAIL = Q(media__gt="") & (Q(thumbnail="") | Q(thumbnail__isnull=True))


def _positive_int(value):
    """Return value as an int if it is a positive number, else None.

    SaveAPI sends sizes as ints, numeric strings or 0 when unknown.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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

    def generate_embedding(self):
        """Generate and save an embedding of the thumbnail through OpenRouter.

        The values are saved with a queryset update, so post_save does not
        fire and no history row is added.

        Returns:
            list[float]: the embedding vector

        Raises:
            ValueError: if the post has no thumbnail, or the vector does not
                fit the 1536-dimension column
            ImproperlyConfigured: if OpenRouter is not configured
            requests.RequestException: if the OpenRouter call fails
        """
        if not self.thumbnail:
            msg = f"Thumbnail file does not exist for post {self.pk}"
            raise ValueError(msg)

        embedding, token_usage = generate_image_embedding(self.thumbnail.url)
        dimensions = self._meta.get_field("embedding").dimensions
        if len(embedding) != dimensions:
            msg = (
                f"Embedding for post {self.pk} has {len(embedding)} dimensions, "
                f"expected {dimensions}"
            )
            raise ValueError(msg)

        self.embedding = embedding
        self.embedding_token_usage = token_usage
        Post.objects.filter(pk=self.pk).update(
            embedding=embedding,
            embedding_token_usage=token_usage,
        )
        logger.info(
            "Generated embedding for post %s (tokens: %d)",
            self.pk,
            token_usage,
        )
        return embedding

    def create_media(self):
        """Create a PostMedia row for each item in raw_data["medias"].

        reference is the item's index, so the rows keep the carousel order.
        Images get their URL as thumbnail_url; videos have no thumbnail URL.
        Rows that already exist are skipped, so calling this again is safe.

        Returns:
            int: number of media items found in raw_data
        """
        medias = (self.raw_data or {}).get("medias")
        if not isinstance(medias, list):
            return 0

        items = []
        for index, media in enumerate(medias):
            url = media.get("url") if isinstance(media, dict) else None
            if not url:
                continue
            items.append(
                PostMedia(
                    post=self,
                    reference=str(index),
                    media_url=url,
                    thumbnail_url=url if media.get("type") == "image" else "",
                    width=_positive_int(media.get("width")),
                    height=_positive_int(media.get("height")),
                ),
            )
        PostMedia.objects.bulk_create(items, ignore_conflicts=True)
        return len(items)

    @classmethod
    def increment_view_count(cls, post_id):
        """Add 1 to a post's view_count with an atomic queryset update.

        Uses .update() instead of .save(), so post_save never fires and no
        simple_history row is added on every view.
        """
        cls.objects.filter(id=post_id).update(view_count=F("view_count") + 1)

    @classmethod
    def download_thumbnail_by_id(cls, post_id):
        """Load a post and run download_thumbnail on it.

        Returns:
            dict: success (bool), post_id and downloaded (bool), or error
        """
        post = (
            cls.objects.select_related("user")
            .only("id", "thumbnail_url", "thumbnail", "user__uuid", "user__username")
            .filter(id=post_id)
            .first()
        )
        if post is None:
            logger.error("Post with ID %s not found", post_id)
            return {"success": False, "error": "Post not found"}

        saved_name = post.download_thumbnail()
        return {"success": True, "post_id": post_id, "downloaded": bool(saved_name)}

    @classmethod
    def process_thumbnail_by_id(cls, post_id):
        """Run process_thumbnail on a post that still needs it.

        A post that is missing, has no thumbnail or is already processed
        returns without touching storage.

        Returns:
            dict: success (bool), post_id and processed (bool)
        """
        post = (
            cls.objects.only("id", "thumbnail")
            .filter(NEEDS_THUMBNAIL_PROCESSING, id=post_id)
            .first()
        )
        if post is None:
            return {"success": True, "post_id": post_id, "processed": False}

        post.process_thumbnail()
        return {"success": True, "post_id": post_id, "processed": True}

    @classmethod
    def generate_embedding_by_id(cls, post_id):
        """Run generate_embedding on a post that still needs one.

        A post that is missing, has no usable thumbnail or already has an
        embedding returns without calling OpenRouter.

        Returns:
            dict: success (bool), post_id and generated (bool), plus
            dimensions when an embedding was saved
        """
        post = (
            cls.objects.only("id", "thumbnail")
            .filter(NEEDS_EMBEDDING, id=post_id)
            .first()
        )
        if post is None:
            return {"success": True, "post_id": post_id, "generated": False}

        embedding = post.generate_embedding()
        return {
            "success": True,
            "post_id": post_id,
            "generated": True,
            "dimensions": len(embedding),
        }

    @classmethod
    def create_media_by_id(cls, post_id):
        """Run create_media on a post that has media but no PostMedia rows.

        Returns:
            dict: success (bool), post_id, created (bool) and media_count (int)
        """
        post = (
            cls.objects.only("id", "raw_data")
            .filter(NEEDS_POST_MEDIA, id=post_id)
            .first()
        )
        if post is None:
            return {
                "success": True,
                "post_id": post_id,
                "created": False,
                "media_count": 0,
            }

        media_count = post.create_media()
        return {
            "success": True,
            "post_id": post_id,
            "created": True,
            "media_count": media_count,
        }


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

    def download_media(self):
        """Download media_url into media and save the file name.

        Videos are stored whole. width and height are read from the file;
        when that fails, the values from SaveAPI are kept. The name is
        written with a conditional queryset update, so a file another worker
        stored first is kept and the new one is deleted. The upload path
        reads post.user.username, so load post__user before calling.

        Returns:
            str or None: saved file name, or None if nothing was saved
        """
        if not self.media_url or self.media:
            return None
        content, extension = download_file_from_url(self.media_url)
        if not (content and extension):
            return None

        fields = {}
        width, height = (_positive_int(size) for size in get_media_size(content))
        if width and height:
            fields = {"width": width, "height": height}

        self.media.save(f"{uuid.uuid4()}.{extension}", ContentFile(content), save=False)
        updated = (
            PostMedia.objects.filter(pk=self.pk)
            .filter(Q(media="") | Q(media__isnull=True))
            .update(media=self.media.name, **fields)
        )
        if not updated:
            self.media.delete(save=False)
            return None
        for name, value in fields.items():
            setattr(self, name, value)
        logger.info("Downloaded media for post media %s", self.pk)
        return self.media.name

    @classmethod
    def download_media_by_id(cls, post_media_id):
        """Load a PostMedia row and run download_media on it.

        Returns:
            dict: success (bool), post_media_id and downloaded (bool), or error
        """
        post_media = (
            cls.objects.select_related("post__user")
            .only(
                "id",
                "media_url",
                "media",
                "post__id",
                "post__user__uuid",
                "post__user__username",
            )
            .filter(id=post_media_id)
            .first()
        )
        if post_media is None:
            logger.error("PostMedia with ID %s not found", post_media_id)
            return {"success": False, "error": "PostMedia not found"}

        saved_name = post_media.download_media()
        return {
            "success": True,
            "post_media_id": post_media_id,
            "downloaded": bool(saved_name),
        }

    def generate_thumbnail(self):
        """Fill thumbnail from the stored media file.

        An image is its own thumbnail, so thumbnail points at the media file
        and nothing is uploaded. For a video, one frame is stored as a JPEG.
        The file is tried as an image first, so a video saved as .bin is not
        stored as an image. The name is written with a conditional queryset
        update; a frame uploaded by a worker that lost the race is deleted.
        The upload path reads post.user.username, so load post__user before
        calling.

        Returns:
            str or None: thumbnail file name, or None if nothing was saved
        """
        if not self.media or self.thumbnail:
            return None

        frame = None
        try:
            with self.media.open("rb") as media_file:
                try:
                    with PILImage.open(media_file):
                        is_image = True
                except (OSError, ValueError):
                    is_image = False
                if not is_image:
                    media_file.seek(0)
                    frame = extract_video_frame(media_file)
        except FileNotFoundError:
            logger.warning("Media file of post media %s is missing", self.pk)
            return None

        if is_image:
            self.thumbnail.name = self.media.name
        elif frame:
            self.thumbnail.save(f"{uuid.uuid4()}.jpg", ContentFile(frame), save=False)
        else:
            logger.warning("No thumbnail could be made for post media %s", self.pk)
            return None

        updated = (
            PostMedia.objects.filter(pk=self.pk)
            .filter(Q(thumbnail="") | Q(thumbnail__isnull=True))
            .update(thumbnail=self.thumbnail.name)
        )
        if not updated:
            if not is_image:
                self.thumbnail.delete(save=False)
            return None
        logger.info("Generated thumbnail for post media %s", self.pk)
        return self.thumbnail.name

    @classmethod
    def generate_thumbnail_by_id(cls, post_media_id):
        """Run generate_thumbnail on a PostMedia row that still needs one.

        A row that is missing, has no media file or already has a thumbnail
        returns without touching storage.

        Returns:
            dict: success (bool), post_media_id and generated (bool)
        """
        post_media = (
            cls.objects.select_related("post__user")
            .only(
                "id",
                "media",
                "thumbnail",
                "post__id",
                "post__user__uuid",
                "post__user__username",
            )
            .filter(NEEDS_MEDIA_THUMBNAIL, id=post_media_id)
            .first()
        )
        if post_media is None:
            return {"success": True, "post_media_id": post_media_id, "generated": False}

        name = post_media.generate_thumbnail()
        return {
            "success": True,
            "post_media_id": post_media_id,
            "generated": bool(name),
        }
