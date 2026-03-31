import hashlib
import logging
from io import BytesIO

import requests
from celery import shared_task
from django.core.files.base import ContentFile
from PIL import Image

from instagram.models import Post
from instagram.models import PostMedia
from instagram.utils import generate_blur_data_url_from_image_url

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def post_generate_blur_data_url(self, post_id: str) -> dict:
    """
    Generate blur data URL for a post in the background.
    Delegates business logic to the utility function.

    Args:
        post_id (str): ID of the post to generate blur data URL for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        logger.exception("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    try:
        # Generate blur data URL using utility function
        blur_data_url = generate_blur_data_url_from_image_url(
            post.thumbnail.url if post.thumbnail else post.thumbnail_url,
        )

        # Save to the model
        post.blur_data_url = blur_data_url
        post.save()

        logger.info(
            "Successfully generated blur data URL for post %s",
            post_id,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Successfully generated blur data URL",
            "post_id": post_id,
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error generating blur data URL for post %s "
                "(attempt %s/%s): %s",
                post_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate blur data URL for post %s after %s attempts",
            post_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "post_id": post_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def periodic_generate_post_blur_data_urls():
    """
    Automatically generate blur data URLs for posts that don't have them yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        # Get all posts without blur_data_url
        posts = Post.objects.filter(blur_data_url="")
        total_posts = posts.count()

        if total_posts == 0:
            logger.info("No posts found without blur data URL")
            return {
                "success": True,
                "message": "No posts to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting blur data URL generation for %d posts",
            total_posts,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for post in posts:
            try:
                # Queue the blur data URL generation task
                task_result = post_generate_blur_data_url.delay(post.id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued blur data URL generation for "
                    "post: %s (task: %s)",
                    post.id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue blur data URL generation for "
                    f"post {post.id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing blur data URL generation for post %s",
                    post.id,
                )

        logger.info(
            "Blur data URL generation queuing completed: "
            "%d queued, %d errors out of %d total posts",
            queued_count,
            error_count,
            total_posts,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Blur data URL generation tasks queued",
            "total": total_posts,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_generate_post_blur_data_urls")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def post_media_generate_blur_data_url(self, post_media_id: int) -> dict:
    """
    Generate blur data URL for a post media in the background.
    Delegates business logic to the utility function.

    Args:
        post_media_id (int): ID of the post media to generate blur data URL for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post_media = PostMedia.objects.get(id=post_media_id)
    except PostMedia.DoesNotExist:
        logger.exception("PostMedia with ID %s not found", post_media_id)
        return {"success": False, "error": "PostMedia not found"}

    try:
        # Generate blur data URL using utility function
        image_url = (
            post_media.thumbnail.url
            if post_media.thumbnail
            else post_media.thumbnail_url
        )
        blur_data_url = generate_blur_data_url_from_image_url(image_url)

        # Save to the model
        post_media.blur_data_url = blur_data_url
        post_media.save()

        logger.info(
            "Successfully generated blur data URL for post media %s",
            post_media_id,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Successfully generated blur data URL",
            "post_media_id": post_media_id,
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error generating blur data URL for post media %s "
                "(attempt %s/%s): %s",
                post_media_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate blur data URL for post media %s after %s attempts",
            post_media_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "post_media_id": post_media_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def periodic_generate_post_media_blur_data_urls():
    """
    Automatically generate blur data URLs for post media that don't have them yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        # Get all post media without blur_data_url
        post_media_items = PostMedia.objects.filter(blur_data_url="")
        total_items = post_media_items.count()

        if total_items == 0:
            logger.info("No post media found without blur data URL")
            return {
                "success": True,
                "message": "No post media to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting blur data URL generation for %d post media items",
            total_items,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for post_media in post_media_items:
            try:
                # Queue the blur data URL generation task
                task_result = post_media_generate_blur_data_url.delay(post_media.id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued blur data URL generation for "
                    "post media: %s (task: %s)",
                    post_media.id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue blur data URL generation for "
                    f"post media {post_media.id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing blur data URL generation for post media %s",
                    post_media.id,
                )

        logger.info(
            "Blur data URL generation queuing completed: "
            "%d queued, %d errors out of %d total post media items",
            queued_count,
            error_count,
            total_items,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Blur data URL generation tasks queued",
            "total": total_items,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception(
            "Critical error in periodic_generate_post_media_blur_data_urls",
        )
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_post_thumbnail_from_url(self, post_id):
    """
    Download post thumbnail from URL if content has changed.
    Uses hash comparison to detect actual image content changes.

    Args:
        post_id (str): ID of the post to download thumbnail for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        logger.exception("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    if not post.thumbnail_url:
        logger.info("No thumbnail URL for post %s", post_id)
        return {"success": False, "error": "No thumbnail URL"}

    try:
        # Download image from URL
        response = requests.get(post.thumbnail_url, timeout=30)
        response.raise_for_status()

        # Calculate hash of downloaded image content
        new_image_content = response.content
        new_image_hash = hashlib.sha256(new_image_content).hexdigest()

        # Get hash of existing thumbnail if it exists
        existing_image_hash = None
        if post.thumbnail:
            try:
                with post.thumbnail.open("rb") as f:
                    existing_content = f.read()
                    existing_image_hash = hashlib.sha256(existing_content).hexdigest()
            except OSError as e:
                logger.warning(
                    "Could not read existing thumbnail for post %s: %s",
                    post_id,
                    e,
                )

        # Compare hashes - only update if different
        if existing_image_hash == new_image_hash:
            logger.info("Thumbnail unchanged for post %s", post_id)
            return {"success": True, "message": "No changes detected"}

        # Get image dimensions
        try:
            image = Image.open(BytesIO(new_image_content))
            width, height = image.size
        except (OSError, ValueError) as e:
            logger.warning(
                "Could not determine image dimensions for post %s: %s",
                post_id,
                e,
            )
            width, height = None, None

        # Save new image
        filename = f"post_{post_id}_thumbnail.jpg"

        # Save the new image
        post.thumbnail.save(
            filename,
            ContentFile(new_image_content),
            save=False,
        )

        # Update using queryset to avoid triggering signal again
        Post.objects.filter(id=post.id).update(
            thumbnail=post.thumbnail.name,
            width=width,
            height=height,
        )

        logger.info(
            "Thumbnail downloaded for post %s (dimensions: %sx%s)",
            post_id,
            width,
            height,
        )

        # Queue thumbnail insight generation task
        generate_post_thumbnail_insight.delay(post_id)
        logger.info(
            "Thumbnail insight generation task queued for post %s",
            post_id,
        )
        return {  # noqa: TRY300
            "success": True,
            "message": "Thumbnail downloaded",
            "old_hash": existing_image_hash,
            "new_hash": new_image_hash,
            "width": width,
            "height": height,
        }

    except (requests.RequestException, OSError) as e:
        # Retryable errors: network issues, S3 timeouts, temporary file access issues
        logger.warning(
            "Retryable error downloading thumbnail for post %s (attempt %s/%s): %s",
            post_id,
            self.request.retries + 1,
            self.max_retries + 1,
            e,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        logger.exception(
            "Max retries exceeded for thumbnail download for post %s",
            post_id,
        )
        return {"success": False, "error": f"Max retries exceeded: {e!s}"}

    except Exception as e:
        # Non-retryable errors: permanent failures
        logger.exception(
            "Permanent error downloading thumbnail for post %s",
            post_id,
        )
        return {"success": False, "error": f"Permanent error: {e!s}"}


def _download_file_from_url(url: str, timeout: int = 30) -> bytes:
    """
    Download file content from URL.

    Args:
        url: URL to download from
        timeout: Request timeout in seconds

    Returns:
        File content as bytes

    Raises:
        requests.RequestException: If download fails
    """
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _get_file_hash(file_field) -> str | None:
    """
    Calculate SHA256 hash of a file field.

    Args:
        file_field: Django FileField or ImageField instance

    Returns:
        Hex digest of file hash, or None if file doesn't exist or can't be read
    """
    if not file_field:
        return None

    try:
        with file_field.open("rb") as f:
            content = f.read()
            return hashlib.sha256(content).hexdigest()
    except OSError as e:
        logger.warning("Could not read file: %s", e)
        return None


def _determine_file_extension(response: requests.Response, url: str) -> str:
    """
    Determine file extension from response headers or URL.

    Args:
        response: HTTP response object
        url: Original URL

    Returns:
        File extension (without dot)
    """
    content_type = response.headers.get("content-type", "")
    if "video" in content_type:
        return "mp4"
    if "image" in content_type:
        return "jpg"

    # Fallback: try to get from URL
    return url.split(".")[-1].split("?")[0] or "jpg"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_post_thumbnail_insight(self, post_id: str) -> dict:
    """
    Generate AI-powered insight for a post thumbnail using OpenAI Vision API.
    This is a background task that calls the Post model's
    generate_thumbnail_insight method.

    Args:
        post_id (str): ID of the post to generate insight for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        logger.exception("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    # Check if thumbnail exists
    if not post.thumbnail:
        logger.warning(
            "No thumbnail file for post %s, cannot generate insight",
            post_id,
        )
        return {"success": False, "error": "No thumbnail file"}

    # Check if insight already exists
    if post.thumbnail_insight:
        logger.info("Thumbnail insight already exists for post %s", post_id)
        return {"success": True, "message": "Insight already exists"}

    try:
        # Generate the insight
        post.generate_thumbnail_insight()

        logger.info(
            "Successfully generated thumbnail insight for post %s (tokens: %s)",
            post_id,
            post.thumbnail_insight_token_usage,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Successfully generated thumbnail insight",
            "post_id": post_id,
            "token_usage": post.thumbnail_insight_token_usage,
        }

    except ValueError as e:
        # Non-retryable error (e.g., thumbnail doesn't exist)
        logger.exception(
            "ValueError generating thumbnail insight for post %s",
            post_id,
        )
        return {"success": False, "error": f"ValueError: {e!s}"}

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
            "openai",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error generating thumbnail insight for post %s "
                "(attempt %s/%s): %s",
                post_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate thumbnail insight for post %s after %s attempts",
            post_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "post_id": post_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def periodic_generate_post_thumbnail_insights():
    """
    Automatically generate thumbnail insights for posts that have thumbnails
    but don't have insights yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        # Get all posts with thumbnails but no insights
        posts = Post.objects.filter(
            thumbnail__isnull=False,
            thumbnail_insight="",
        )
        total_posts = posts.count()

        if total_posts == 0:
            logger.info("No posts found without thumbnail insights")
            return {
                "success": True,
                "message": "No posts to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting thumbnail insight generation for %d posts",
            total_posts,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for post in posts:
            try:
                # Queue the thumbnail insight generation task
                task_result = generate_post_thumbnail_insight.delay(post.id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued thumbnail insight generation for "
                    "post: %s (task: %s)",
                    post.id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue thumbnail insight generation for "
                    f"post {post.id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing thumbnail insight generation for post %s",
                    post.id,
                )

        logger.info(
            "Thumbnail insight generation queuing completed: "
            "%d queued, %d errors out of %d total posts",
            queued_count,
            error_count,
            total_posts,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Thumbnail insight generation tasks queued",
            "total": total_posts,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_generate_post_thumbnail_insights")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_post_media_thumbnail_from_url(self, post_media_id):
    """
    Download post media thumbnail from URL if content has changed.
    Uses hash comparison to detect actual image content changes.

    Args:
        post_media_id (int): ID of the post media to download thumbnail for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post_media = PostMedia.objects.get(id=post_media_id)
    except PostMedia.DoesNotExist:
        logger.exception("PostMedia with ID %s not found", post_media_id)
        return {"success": False, "error": "PostMedia not found"}

    if not post_media.thumbnail_url:
        logger.info("No thumbnail URL for post media %s", post_media_id)
        return {"success": False, "error": "No thumbnail URL"}

    try:
        # Download image from URL
        new_image_content = _download_file_from_url(post_media.thumbnail_url)
        new_image_hash = hashlib.sha256(new_image_content).hexdigest()

        # Get hash of existing thumbnail if it exists
        existing_image_hash = _get_file_hash(post_media.thumbnail)

        # Compare hashes - only update if different
        if existing_image_hash == new_image_hash:
            logger.info("Thumbnail unchanged for post media %s", post_media_id)
            return {"success": True, "message": "No changes detected"}

        # Get image dimensions
        try:
            image = Image.open(BytesIO(new_image_content))
            width, height = image.size
        except (OSError, ValueError) as e:
            logger.warning(
                "Could not determine image dimensions for post media %s: %s",
                post_media_id,
                e,
            )
            width, height = None, None

        # Save new image
        filename = f"post_media_{post_media_id}_thumbnail.jpg"

        # Save the new image
        post_media.thumbnail.save(
            filename,
            ContentFile(new_image_content),
            save=False,
        )

        # Update using queryset to avoid triggering signal again
        PostMedia.objects.filter(id=post_media.id).update(
            thumbnail=post_media.thumbnail.name,
            width=width,
            height=height,
        )

        logger.info(
            "Thumbnail downloaded for post media %s (dimensions: %sx%s)",
            post_media_id,
            width,
            height,
        )
        return {  # noqa: TRY300
            "success": True,
            "message": "Thumbnail downloaded",
            "old_hash": existing_image_hash,
            "new_hash": new_image_hash,
            "width": width,
            "height": height,
        }

    except (requests.RequestException, OSError) as e:
        # Retryable errors: network issues, S3 timeouts, temporary file access issues
        logger.warning(
            "Retryable error downloading thumbnail for post media %s "
            "(attempt %s/%s): %s",
            post_media_id,
            self.request.retries + 1,
            self.max_retries + 1,
            e,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        logger.exception(
            "Max retries exceeded for thumbnail download for post media %s",
            post_media_id,
        )
        return {"success": False, "error": f"Max retries exceeded: {e!s}"}

    except Exception as e:
        # Non-retryable errors: permanent failures
        logger.exception(
            "Permanent error downloading thumbnail for post media %s",
            post_media_id,
        )
        return {"success": False, "error": f"Permanent error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_post_media_from_url(self, post_media_id):
    """
    Download post media file from URL if content has changed.
    Uses hash comparison to detect actual media content changes.

    Args:
        post_media_id (int): ID of the post media to download media for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post_media = PostMedia.objects.get(id=post_media_id)
    except PostMedia.DoesNotExist:
        logger.exception("PostMedia with ID %s not found", post_media_id)
        return {"success": False, "error": "PostMedia not found"}

    if not post_media.media_url:
        logger.info("No media URL for post media %s", post_media_id)
        return {"success": False, "error": "No media URL"}

    try:
        # Download media from URL
        response = requests.get(post_media.media_url, timeout=30)
        response.raise_for_status()

        # Calculate hash of downloaded media content
        new_media_content = response.content
        new_media_hash = hashlib.sha256(new_media_content).hexdigest()

        # Get hash of existing media if it exists
        existing_media_hash = _get_file_hash(post_media.media)

        # Compare hashes - only update if different
        if existing_media_hash == new_media_hash:
            logger.info("Media unchanged for post media %s", post_media_id)
            return {"success": True, "message": "No changes detected"}

        # Determine file extension from content-type or URL
        extension = _determine_file_extension(response, post_media.media_url)

        # Save new media
        filename = f"post_media_{post_media_id}_media.{extension}"

        # Save the new media
        post_media.media.save(
            filename,
            ContentFile(new_media_content),
            save=False,
        )

        # Update using queryset to avoid triggering signal again
        PostMedia.objects.filter(id=post_media.id).update(
            media=post_media.media.name,
        )

        logger.info("Media downloaded for post media %s", post_media_id)
        return {  # noqa: TRY300
            "success": True,
            "message": "Media downloaded",
            "old_hash": existing_media_hash,
            "new_hash": new_media_hash,
        }

    except (requests.RequestException, OSError) as e:
        # Retryable errors: network issues, S3 timeouts, temporary file access issues
        logger.warning(
            "Retryable error downloading media for post media %s (attempt %s/%s): %s",
            post_media_id,
            self.request.retries + 1,
            self.max_retries + 1,
            e,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        logger.exception(
            "Max retries exceeded for media download for post media %s",
            post_media_id,
        )
        return {"success": False, "error": f"Max retries exceeded: {e!s}"}

    except Exception as e:
        # Non-retryable errors: permanent failures
        logger.exception(
            "Permanent error downloading media for post media %s",
            post_media_id,
        )
        return {"success": False, "error": f"Permanent error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_post_embedding(self, post_id: str) -> dict:  # noqa: PLR0911
    """
    Generate embedding vector for a post using OpenAI embeddings API.
    This is a background task that calls the Post model's generate_embedding method.

    Args:
        post_id (str): ID of the post to generate embedding for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        logger.exception("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    # Check if embedding already exists
    if post.embedding is not None:
        logger.info("Embedding already exists for post %s", post_id)
        return {"success": True, "message": "Embedding already exists"}

    # Check if post has thumbnail_insight (required for embedding)
    if not post.thumbnail_insight:
        logger.warning(
            "Post %s has no thumbnail_insight, cannot generate embedding",
            post_id,
        )
        return {
            "success": False,
            "error": "No thumbnail_insight available",
        }

    try:
        # Generate the embedding
        embedding = post.generate_embedding()

        if embedding is None:
            return {
                "success": False,
                "error": "Embedding generation returned None",
                "post_id": post_id,
            }

        logger.info(
            "Successfully generated embedding for post %s (dimensions: %d)",
            post_id,
            len(embedding),
        )

        return {
            "success": True,
            "message": "Successfully generated embedding",
            "post_id": post_id,
            "dimensions": len(embedding),
        }

    except ValueError as e:
        # Non-retryable error (e.g., empty caption and insight)
        logger.exception("ValueError generating embedding for post %s", post_id)
        return {"success": False, "error": f"ValueError: {e!s}"}

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
            "openai",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error generating embedding for post %s (attempt %s/%s): %s",
                post_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate embedding for post %s after %s attempts",
            post_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "post_id": post_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def periodic_generate_post_embeddings():
    """
    Automatically generate embeddings for posts that have thumbnail_insight
    but don't have embeddings yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        # Get all posts without embeddings that have thumbnail_insight
        posts = Post.objects.filter(
            embedding__isnull=True,
            thumbnail_insight__isnull=False,
            thumbnail_insight__gt="",
        )
        total_posts = posts.count()

        if total_posts == 0:
            logger.info("No posts found without embeddings")
            return {
                "success": True,
                "message": "No posts to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting embedding generation for %d posts",
            total_posts,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for post in posts:
            try:
                # Queue the embedding generation task
                task_result = generate_post_embedding.delay(post.id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued embedding generation for post: %s (task: %s)",
                    post.id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue embedding generation for post {post.id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing embedding generation for post %s",
                    post.id,
                )

        logger.info(
            "Embedding generation queuing completed: "
            "%d queued, %d errors out of %d total posts",
            queued_count,
            error_count,
            total_posts,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Embedding generation tasks queued",
            "total": total_posts,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_generate_post_embeddings")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def moderate_post_content(self, post_id: str) -> dict:
    """
    Moderate the content of a single post using OpenAI's moderation API.
    This task is retryable with exponential backoff.

    Args:
        post_id: The primary key of the Post to moderate.

    Returns:
        dict: Result summary with success status and post_id.
    """
    try:
        post = Post.objects.get(id=post_id)
        post.moderate_content()
        logger.info("Successfully moderated post %s", post_id)
        return {"success": True, "post_id": post_id}  # noqa: TRY300
    except Post.DoesNotExist:
        logger.exception("Post %s not found", post_id)
        return {"success": False, "post_id": post_id, "error": "Post not found"}
    except Exception as exc:
        logger.exception("Error moderating post %s", post_id)
        raise self.retry(exc=exc)  # noqa: B904


@shared_task
def periodic_moderate_post_content():
    """
    Automatically moderate posts that have thumbnails but have not been moderated yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed.
    """
    try:
        posts = Post.objects.filter(
            thumbnail__isnull=False,
            moderated_at__isnull=True,
        )
        total_posts = posts.count()

        if total_posts == 0:
            logger.info("No posts found pending moderation")
            return {
                "success": True,
                "message": "No posts to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info("Starting content moderation for %d posts", total_posts)

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for post in posts:
            try:
                task_result = moderate_post_content.delay(post.id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued moderation for post: %s (task: %s)",
                    post.id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = f"Failed to queue moderation for post {post.id}: {e!s}"
                errors.append(error_msg)
                logger.exception(
                    "Error queuing moderation for post %s",
                    post.id,
                )

        logger.info(
            "Content moderation queuing completed: %d queued, %d errors out of %d total posts",  # noqa: E501
            queued_count,
            error_count,
            total_posts,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Content moderation tasks queued",
            "total": total_posts,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_moderate_post_content")
        return {"success": False, "error": f"Critical error: {e!s}"}
