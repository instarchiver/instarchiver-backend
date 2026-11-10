import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import F
from django.db.models import Q
from django.utils import timezone

from instagram.models import Post
from instagram.tasks.story import FILE_RETRY
from instagram.tasks.story import _queue_each

logger = logging.getLogger(__name__)

# Instagram CDN URLs expire, so older posts are not worth retrying.
THUMBNAIL_DOWNLOAD_WINDOW = timedelta(days=7)

# Posts whose stored thumbnail still needs a blur placeholder or a size.
NEEDS_THUMBNAIL_PROCESSING = Q(thumbnail__gt="") & (
    Q(blur_data_url="") | Q(width__isnull=True) | Q(height__isnull=True)
)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=3, default_retry_delay=10, ignore_result=True)
def increment_post_view_count(self, post_id: str) -> None:
    """Atomically increment a post's view_count by 1.

    Uses .update() instead of .save() so this never triggers the post_save
    signal (avoiding noisy simple_history snapshot rows on every view).
    """
    Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)


@shared_task(bind=True, **FILE_RETRY)
def download_post_thumbnail_from_url(self, post_id):
    """Download a post's thumbnail from thumbnail_url.

    Only storage and database errors are retried. A failed download returns
    downloaded=False, and periodic_download_post_thumbnails queues the post
    again on its next run.

    Args:
        post_id (str): primary key of the post

    Returns:
        dict: success (bool), post_id and downloaded (bool)
    """
    post = (
        Post.objects.select_related("user")
        .only("id", "thumbnail_url", "thumbnail", "user__uuid", "user__username")
        .filter(id=post_id)
        .first()
    )
    if post is None:
        logger.error("Post with ID %s not found", post_id)
        return {"success": False, "error": "Post not found"}

    saved_name = post.download_thumbnail()
    return {"success": True, "post_id": post_id, "downloaded": bool(saved_name)}


@shared_task
def process_post_thumbnail(post_id):
    """Fill a post's blur_data_url, width and height from its thumbnail.

    A post that is missing, has no thumbnail or is already processed returns
    without touching storage, so duplicate queue entries cost one query.
    There is no retry. A failed post still matches
    NEEDS_THUMBNAIL_PROCESSING, so periodic_process_post_thumbnails queues
    it again on its next run.

    Args:
        post_id (str): primary key of the post

    Returns:
        dict: success (bool), post_id and processed (bool)
    """
    post = (
        Post.objects.only("id", "thumbnail")
        .filter(NEEDS_THUMBNAIL_PROCESSING, id=post_id)
        .first()
    )
    if post is None:
        return {"success": True, "post_id": post_id, "processed": False}

    post.process_thumbnail()
    return {"success": True, "post_id": post_id, "processed": True}


# ---------------------------------------------------------------------------
# Periodic tasks (scheduled by Celery Beat)
# ---------------------------------------------------------------------------


@shared_task
def periodic_download_post_thumbnails():
    """Queue thumbnail downloads for recent posts that have no thumbnail.

    Only posts archived in the last THUMBNAIL_DOWNLOAD_WINDOW are queued.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    posts = Post.objects.filter(
        thumbnail_url__gt="",
        created_at__gte=timezone.now() - THUMBNAIL_DOWNLOAD_WINDOW,
    ).filter(Q(thumbnail="") | Q(thumbnail__isnull=True))
    return _queue_each(download_post_thumbnail_from_url, posts)


@shared_task
def periodic_process_post_thumbnails():
    """Queue blur and size processing for posts with an unprocessed thumbnail.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    posts = Post.objects.filter(NEEDS_THUMBNAIL_PROCESSING)
    return _queue_each(process_post_thumbnail, posts)
