import logging

from celery import shared_task
from django.db.models import F
from django.db.models import Q

from instagram.models import Story
from instagram.models.story import is_video_filename
from instagram.utils import generate_blur_data_url_from_image_url

logger = logging.getLogger(__name__)

# Retries after 60s, 120s and 240s.
FILE_RETRY = {
    "autoretry_for": (Exception,),
    "retry_backoff": 60,
    "retry_jitter": False,
    "max_retries": 3,
}


def _save_story_file(story_id, field, make_file):
    """Run make_file on a story and store the resulting file name.

    The name is written with a queryset update, so post_save does not fire
    again.

    Args:
        story_id (str): primary key of the story
        field (str): file field to update, "thumbnail" or "media"
        make_file (callable): Story method that attaches a file and returns
            its name or None, e.g. Story.download_thumbnail

    Returns:
        tuple: (Story or None, saved file name str or None). The story is
        None when it does not exist.
    """
    story = Story.objects.filter(story_id=story_id).first()
    if story is None:
        logger.error("Story with ID %s not found", story_id)
        return None, None

    saved_name = make_file(story)
    if saved_name:
        Story.objects.filter(story_id=story_id).update(**{field: saved_name})
    return story, saved_name


def _queue_each(task, stories):
    """Queue task once for every story in a queryset.

    Args:
        task (celery.Task): task that takes a story_id
        stories (QuerySet): stories to queue

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    story_ids = list(stories.values_list("story_id", flat=True))
    errors = 0
    for story_id in story_ids:
        try:
            task.delay(story_id)
        except Exception:
            errors += 1
            logger.exception("Failed to queue %s for story %s", task.name, story_id)

    logger.info(
        "Queued %s for %d of %d stories",
        task.name,
        len(story_ids) - errors,
        len(story_ids),
    )
    return {
        "success": True,
        "total": len(story_ids),
        "queued": len(story_ids) - errors,
        "errors": errors,
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=10, ignore_result=True)
def increment_story_view_count(self, story_id):
    """Add 1 to a story's view_count with an atomic queryset update.

    Args:
        story_id (str): primary key of the story
    """
    Story.objects.filter(story_id=story_id).update(view_count=F("view_count") + 1)


@shared_task(bind=True, **FILE_RETRY)
def download_story_thumbnail_from_url(self, story_id):
    """Download a story's thumbnail from thumbnail_url.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool), story_id and downloaded (bool)
    """
    story, saved_name = _save_story_file(
        story_id,
        "thumbnail",
        Story.download_thumbnail,
    )
    if story is None:
        return {"success": False, "error": "Story not found"}
    return {"success": True, "story_id": story_id, "downloaded": bool(saved_name)}


@shared_task(bind=True, **FILE_RETRY)
def download_story_media_from_url(self, story_id):
    """Download a story's media file from media_url.

    Video stories from SaveAPI have no thumbnail URL, so once the video is
    stored a task is queued to cut a thumbnail from it.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool), story_id and downloaded (bool)
    """
    story, saved_name = _save_story_file(story_id, "media", Story.download_media)
    if story is None:
        return {"success": False, "error": "Story not found"}

    if (
        saved_name
        and not story.thumbnail_url
        and not story.thumbnail
        and is_video_filename(saved_name)
    ):
        generate_story_thumbnail_from_media.delay(story_id)
    return {"success": True, "story_id": story_id, "downloaded": bool(saved_name)}


@shared_task(bind=True, **FILE_RETRY)
def generate_story_thumbnail_from_media(self, story_id):
    """Cut a thumbnail for a video story from its stored media file.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool), story_id and generated (bool)
    """
    story, saved_name = _save_story_file(
        story_id,
        "thumbnail",
        Story.generate_thumbnail_from_media,
    )
    if story is None:
        return {"success": False, "error": "Story not found"}
    return {"success": True, "story_id": story_id, "generated": bool(saved_name)}


@shared_task
def story_generate_blur_data_url(story_id):
    """Generate a blur placeholder for a story's thumbnail.

    There is no retry. A failed story keeps an empty blur_data_url, so
    auto_generate_story_blur_data_urls queues it again on its next run.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool) and story_id, or error (str)
    """
    story = Story.objects.filter(story_id=story_id).first()
    if story is None:
        logger.error("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    image_url = story.thumbnail.url if story.thumbnail else story.thumbnail_url
    if not image_url:
        # Video stories get a thumbnail only after the media is downloaded.
        return {"success": False, "error": "No thumbnail", "story_id": story_id}

    blur_data_url = generate_blur_data_url_from_image_url(image_url)
    # A full save() could overwrite file fields a download task just set.
    Story.objects.filter(story_id=story_id).update(blur_data_url=blur_data_url)
    logger.info("Generated blur data URL for story %s", story_id)
    return {"success": True, "story_id": story_id}


@shared_task
def auto_generate_story_blur_data_urls():
    """Queue blur generation for stories that have an image but no blur yet.

    Run periodically by Celery Beat.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    stories = Story.objects.filter(blur_data_url="").filter(
        Q(thumbnail__gt="") | Q(thumbnail_url__gt=""),
    )
    return _queue_each(story_generate_blur_data_url, stories)


@shared_task
def generate_story_embedding(story_id):
    """Generate an embedding for a story's thumbnail.

    There is no retry, because OpenRouter calls cost money. A failed story
    keeps a null embedding, so periodic_generate_story_embeddings queues it
    again on its next run.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool) with story_id and dimensions, or error (str)
    """
    story = Story.objects.filter(story_id=story_id).first()
    if story is None:
        logger.error("Story with ID %s not found", story_id)
        return {"success": False, "error": "Story not found"}

    if story.embedding is not None:
        return {"success": True, "message": "Embedding already exists"}

    if not story.thumbnail:
        logger.warning("Story %s has no thumbnail, skipping embedding", story_id)
        return {"success": False, "error": "No thumbnail file"}

    embedding = story.generate_embedding()
    return {"success": True, "story_id": story_id, "dimensions": len(embedding)}


@shared_task
def periodic_generate_story_embeddings():
    """Queue embedding generation for stories with a thumbnail but no embedding.

    Run periodically by Celery Beat.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    stories = Story.objects.filter(embedding__isnull=True, thumbnail__gt="")
    return _queue_each(generate_story_embedding, stories)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def moderate_story_content(self, story_id):
    """Moderate a story's thumbnail with the OpenAI moderation API.

    Any error is retried up to 3 times, 60 seconds apart.

    Args:
        story_id (str): primary key of the story

    Returns:
        dict: success (bool) and story_id, plus error (str) on failure
    """
    story = Story.objects.filter(story_id=story_id).first()
    if story is None:
        logger.error("Story %s not found", story_id)
        return {"success": False, "story_id": story_id, "error": "Story not found"}

    story.moderate_content()
    logger.info("Moderated story %s", story_id)
    return {"success": True, "story_id": story_id}


@shared_task
def periodic_moderate_story_content():
    """Queue moderation for stories with a thumbnail that were never moderated.

    Run periodically by Celery Beat.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    stories = Story.objects.filter(thumbnail__gt="", moderated_at__isnull=True)
    return _queue_each(moderate_story_content, stories)
