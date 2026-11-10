from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from instagram.models import Post
from instagram.models import PostMedia
from instagram.models.post import NEEDS_EMBEDDING
from instagram.models.post import NEEDS_MEDIA_THUMBNAIL
from instagram.models.post import NEEDS_POST_MEDIA
from instagram.models.post import NEEDS_THUMBNAIL_PROCESSING
from instagram.tasks.story import FILE_RETRY
from instagram.tasks.story import _queue_each

# Instagram CDN URLs expire, so older posts are not worth retrying.
THUMBNAIL_DOWNLOAD_WINDOW = timedelta(days=7)

# Each post costs one paid OpenRouter call, so a run queues at most this many.
EMBEDDING_BATCH_SIZE = 500

# Media whose thumbnail still fails after this long is given up on.
MEDIA_THUMBNAIL_WINDOW = timedelta(days=14)

# Each task reads a whole file from storage, so a run queues at most this many.
MEDIA_THUMBNAIL_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=3, default_retry_delay=10, ignore_result=True)
def increment_post_view_count(self, post_id: str) -> None:
    """Atomically increment a post's view_count by 1.

    Uses .update() instead of .save() so this never triggers the post_save
    signal (avoiding noisy simple_history snapshot rows on every view).
    """
    return Post.increment_view_count(post_id)


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
    return Post.download_thumbnail_by_id(post_id)


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
    return Post.process_thumbnail_by_id(post_id)


@shared_task
def generate_post_embedding(post_id):
    """Generate an embedding for a post's thumbnail.

    A post that is missing, has no usable thumbnail or already has an
    embedding returns without calling OpenRouter. There is no retry, because
    OpenRouter calls cost money. A failed post keeps a null embedding, so
    periodic_generate_post_embeddings queues it again on a later run.

    Args:
        post_id (str): primary key of the post

    Returns:
        dict: success (bool), post_id and generated (bool), plus dimensions
        when an embedding was saved
    """
    return Post.generate_embedding_by_id(post_id)


@shared_task
def create_post_media(post_id):
    """Create the PostMedia rows of a post from its raw_data.

    A post that is missing, has no usable media or already has rows returns
    without changes.

    Args:
        post_id (str): primary key of the post

    Returns:
        dict: success (bool), post_id, created (bool) and media_count (int)
    """
    return Post.create_media_by_id(post_id)


@shared_task(bind=True, **FILE_RETRY)
def download_post_media_from_url(self, post_media_id):
    """Download a PostMedia file from media_url.

    Only storage and database errors are retried. A failed download returns
    downloaded=False, and periodic_download_post_media queues it again.

    Args:
        post_media_id (int): primary key of the PostMedia row

    Returns:
        dict: success (bool), post_media_id and downloaded (bool)
    """
    return PostMedia.download_media_by_id(post_media_id)


@shared_task(bind=True, **FILE_RETRY)
def generate_post_media_thumbnail(self, post_media_id):
    """Make a PostMedia thumbnail from its stored media file.

    Only storage and database errors are retried. A row that gets no
    thumbnail is queued again by periodic_generate_post_media_thumbnails.

    Args:
        post_media_id (int): primary key of the PostMedia row

    Returns:
        dict: success (bool), post_media_id and generated (bool)
    """
    return PostMedia.generate_thumbnail_by_id(post_media_id)


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


@shared_task
def periodic_generate_post_embeddings():
    """Queue embeddings for the newest posts with a thumbnail but no embedding.

    At most EMBEDDING_BATCH_SIZE posts are queued per run, so a large backlog
    is worked through over several runs.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    posts = Post.objects.filter(NEEDS_EMBEDDING).order_by("-created_at")[
        :EMBEDDING_BATCH_SIZE
    ]
    return _queue_each(generate_post_embedding, posts)


@shared_task
def periodic_create_post_media():
    """Queue PostMedia creation for posts whose media rows do not exist yet.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    return _queue_each(create_post_media, Post.objects.filter(NEEDS_POST_MEDIA))


@shared_task
def periodic_download_post_media():
    """Queue downloads for recent PostMedia rows that have no file yet.

    Only media of posts archived in the last THUMBNAIL_DOWNLOAD_WINDOW are
    queued, because the CDN URLs expire.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    post_media = PostMedia.objects.filter(
        media_url__gt="",
        post__created_at__gte=timezone.now() - THUMBNAIL_DOWNLOAD_WINDOW,
    ).filter(Q(media="") | Q(media__isnull=True))
    return _queue_each(download_post_media_from_url, post_media)


@shared_task
def periodic_generate_post_media_thumbnails():
    """Queue thumbnails for the newest stored media that have none.

    Only media of posts archived in the last MEDIA_THUMBNAIL_WINDOW are
    queued, so a file that never yields a thumbnail is not read forever. At
    most MEDIA_THUMBNAIL_BATCH_SIZE rows are queued per run.

    Returns:
        dict: success (bool), total, queued and errors (int)
    """
    rows = PostMedia.objects.filter(
        NEEDS_MEDIA_THUMBNAIL,
        post__created_at__gte=timezone.now() - MEDIA_THUMBNAIL_WINDOW,
    ).order_by("-id")[:MEDIA_THUMBNAIL_BATCH_SIZE]
    return _queue_each(generate_post_media_thumbnail, rows)
