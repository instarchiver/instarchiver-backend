import logging

from celery import shared_task
from django.db.models import F

from instagram.models import Post
from instagram.models import PostMedia
from instagram.utils import generate_blur_data_url_from_image_url

logger = logging.getLogger(__name__)

# --- List of periodic tasks related to posts ---

# periodic_generate_post_blur_data_urls

# --- End of periodic tasks related to posts ---


@shared_task(bind=True, max_retries=3, default_retry_delay=10, ignore_result=True)
def increment_post_view_count(self, post_id: str) -> None:
    """Atomically increment a post's view_count by 1.

    Uses .update() instead of .save() so this never triggers the post_save
    signal (avoiding noisy simple_history snapshot rows on every view).
    """
    Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)


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

        if not post.thumbnail:
            logger.error("Post %s does not have a thumbnail", post_id)
            return {
                "success": False,
                "error": "Post does not have a thumbnail",
                "post_id": post_id,
            }
    except Post.DoesNotExist:
        logger.exception("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    try:
        # Generate blur data URL using utility function
        blur_data_url = generate_blur_data_url_from_image_url(post.thumbnail.url)

        # Save to the model
        post.blur_data_url = blur_data_url
        post.save(update_fields=["blur_data_url"])

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

        logger.exception(
            "Failed to generate blur data URL for post %s: %s",
            post_id,
            error_msg,
        )
        raise


@shared_task
def periodic_generate_post_blur_data_urls():
    """
    Automatically generate blur data URLs for posts that don't have them yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """

    logger.info("Starting periodic generation of post blur data URLs")
    posts = Post.objects.filter(blur_data_url="")

    for post in posts:
        try:
            post_generate_blur_data_url.delay(post.id)
            logger.info(
                "Queued blur data URL generation for post %s",
                post.id,
            )
        except Exception:
            logger.exception(
                "Failed to queue blur data URL generation for post %s",
                post.id,
            )

    logger.info("Finished periodic generation of post blur data URLs")
    return {"success": True, "total_queued": posts.count()}


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

    if not post.thumbnail:
        logger.warning(
            "Post %s has no thumbnail file, cannot generate embedding",
            post_id,
        )
        return {
            "success": False,
            "error": "No thumbnail file",
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
    Automatically generate embeddings for posts that have a thumbnail
    but don't have embeddings yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        posts = Post.objects.filter(
            embedding__isnull=True,
            thumbnail__isnull=False,
            thumbnail__gt="",
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
