import logging

from celery import shared_task

from instagram.models import Story
from instagram.utils import generate_blur_data_url_from_image_url

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_story_thumbnail_from_url(self, story_id: str) -> dict:
    """
    Download thumbnail for a story from thumbnail_url.
    Delegates to Story.download_thumbnail() and saves via queryset update
    to avoid re-triggering the post_save signal.
    """
    try:
        story = Story.objects.get(story_id=story_id)
    except Story.DoesNotExist:
        logger.exception("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    try:
        saved_name = story.download_thumbnail()
        if saved_name:
            Story.objects.filter(story_id=story_id).update(thumbnail=saved_name)
            logger.info("Thumbnail downloaded for story %s", story_id)
        return {
            "success": True,
            "story_id": story_id,
            "downloaded": bool(saved_name),
        }
    except Exception as exc:
        countdown = 60 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_story_media_from_url(self, story_id: str) -> dict:
    """
    Download media file for a story from media_url.
    Delegates to Story.download_media() and saves via queryset update
    to avoid re-triggering the post_save signal.
    """
    try:
        story = Story.objects.get(story_id=story_id)
    except Story.DoesNotExist:
        logger.exception("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    try:
        saved_name = story.download_media()
        if saved_name:
            Story.objects.filter(story_id=story_id).update(media=saved_name)
            logger.info("Media downloaded for story %s", story_id)
        return {
            "success": True,
            "story_id": story_id,
            "downloaded": bool(saved_name),
        }
    except Exception as exc:
        countdown = 60 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def story_generate_blur_data_url(self, story_id: str) -> dict:
    """
    Generate blur data URL for a story in the background.
    Delegates business logic to the utility function.

    Args:
        story_id (str): ID of the story to generate blur data URL for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        story = Story.objects.get(story_id=story_id)
    except Story.DoesNotExist:
        logger.exception("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    try:
        # Generate blur data URL using utility function
        # Use thumbnail.url if thumbnail exists, otherwise use thumbnail_url
        image_url = story.thumbnail.url if story.thumbnail else story.thumbnail_url
        blur_data_url = generate_blur_data_url_from_image_url(image_url)

        # Save to the model
        story.blur_data_url = blur_data_url
        story.save()

        logger.info(
            "Successfully generated blur data URL for story %s",
            story_id,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Successfully generated blur data URL",
            "story_id": story_id,
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
                "Retryable error generating blur data URL for story %s "
                "(attempt %s/%s): %s",
                story_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate blur data URL for story %s after %s attempts",
            story_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "story_id": story_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def auto_generate_story_blur_data_urls():
    """
    Automatically generate blur data URLs for stories that don't have them yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        # Get all stories without blur_data_url
        stories = Story.objects.filter(blur_data_url="")
        total_stories = stories.count()

        if total_stories == 0:
            logger.info("No stories found without blur data URL")
            return {
                "success": True,
                "message": "No stories to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting blur data URL generation for %d stories",
            total_stories,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for story in stories:
            try:
                # Queue the blur data URL generation task
                task_result = story_generate_blur_data_url.delay(story.story_id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued blur data URL generation for "
                    "story: %s (task: %s)",
                    story.story_id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue blur data URL generation for "
                    f"story {story.story_id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing blur data URL generation for story %s",
                    story.story_id,
                )

        logger.info(
            "Blur data URL generation queuing completed: "
            "%d queued, %d errors out of %d total stories",
            queued_count,
            error_count,
            total_stories,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Blur data URL generation tasks queued",
            "total": total_stories,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in auto_generate_story_blur_data_urls")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_story_embedding(self, story_id: str) -> dict:  # noqa: PLR0911
    """
    Generate embedding vector for a story using OpenAI embeddings API.
    This is a background task that calls the Story model's generate_embedding method.

    Args:
        story_id (str): ID of the story to generate embedding for

    Returns:
        dict: Operation result with success status and details
    """
    try:
        story = Story.objects.get(story_id=story_id)
    except Story.DoesNotExist:
        logger.exception("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    # Check if embedding already exists
    if story.embedding is not None:
        logger.info("Embedding already exists for story %s", story_id)
        return {"success": True, "message": "Embedding already exists"}

    if not story.thumbnail:
        logger.warning(
            "Story %s has no thumbnail file, cannot generate embedding",
            story_id,
        )
        return {
            "success": False,
            "error": "No thumbnail file",
        }

    try:
        # Generate the embedding
        embedding = story.generate_embedding()

        if embedding is None:
            return {
                "success": False,
                "error": "Embedding generation returned None",
                "story_id": story_id,
            }

        logger.info(
            "Successfully generated embedding for story %s (dimensions: %d)",
            story_id,
            len(embedding),
        )

        return {
            "success": True,
            "message": "Successfully generated embedding",
            "story_id": story_id,
            "dimensions": len(embedding),
        }

    except ValueError as e:
        # Non-retryable error
        logger.exception("ValueError generating embedding for story %s", story_id)
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
                "Retryable error generating embedding for story %s (attempt %s/%s): %s",
                story_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to generate embedding for story %s after %s attempts",
            story_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "story_id": story_id,
            "attempts": self.request.retries + 1,
        }


@shared_task
def periodic_generate_story_embeddings():
    """
    Automatically generate embeddings for stories that have a thumbnail
    but don't have embeddings yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed
    """
    try:
        stories = Story.objects.filter(
            embedding__isnull=True,
            thumbnail__isnull=False,
        )
        total_stories = stories.count()

        if total_stories == 0:
            logger.info("No stories found without embeddings")
            return {
                "success": True,
                "message": "No stories to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info(
            "Starting embedding generation for %d stories",
            total_stories,
        )

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for story in stories:
            try:
                # Queue the embedding generation task
                task_result = generate_story_embedding.delay(story.story_id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued embedding generation for story: %s (task: %s)",
                    story.story_id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue embedding generation for "
                    f"story {story.story_id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing embedding generation for story %s",
                    story.story_id,
                )

        logger.info(
            "Embedding generation queuing completed: "
            "%d queued, %d errors out of %d total stories",
            queued_count,
            error_count,
            total_stories,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Embedding generation tasks queued",
            "total": total_stories,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_generate_story_embeddings")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def moderate_story_content(self, story_id: str) -> dict:
    """
    Moderate the content of a single story using OpenAI's moderation API.
    This task is retryable with exponential backoff.

    Args:
        story_id: The primary key of the Story to moderate.

    Returns:
        dict: Result summary with success status and story_id.
    """
    try:
        story = Story.objects.get(story_id=story_id)
        story.moderate_content()
        logger.info("Successfully moderated story %s", story_id)
        return {"success": True, "story_id": story_id}  # noqa: TRY300
    except Story.DoesNotExist:
        logger.exception("Story %s not found", story_id)
        return {"success": False, "story_id": story_id, "error": "Story not found"}
    except Exception as exc:
        logger.exception("Error moderating story %s", story_id)
        raise self.retry(exc=exc)  # noqa: B904


@shared_task
def periodic_moderate_story_content():
    """
    Automatically moderate stories that have thumbnails but have not been moderated yet.
    This task is designed to be run periodically via Celery Beat.

    Returns:
        dict: Summary of operations performed.
    """
    try:
        stories = Story.objects.filter(
            thumbnail__isnull=False,
            moderated_at__isnull=True,
        )
        total_stories = stories.count()

        if total_stories == 0:
            logger.info("No stories found pending moderation")
            return {
                "success": True,
                "message": "No stories to process",
                "queued": 0,
                "errors": 0,
            }

        logger.info("Starting content moderation for %d stories", total_stories)

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for story in stories:
            try:
                task_result = moderate_story_content.delay(story.story_id)
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued moderation for story: %s (task: %s)",
                    story.story_id,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue moderation for story {story.story_id}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing moderation for story %s",
                    story.story_id,
                )

        logger.info(
            "Content moderation queuing completed: %d queued, %d errors out of %d total stories",  # noqa: E501
            queued_count,
            error_count,
            total_stories,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Content moderation tasks queued",
            "total": total_stories,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in periodic_moderate_story_content")
        return {"success": False, "error": f"Critical error: {e!s}"}
