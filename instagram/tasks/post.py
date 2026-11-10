from celery import shared_task
from django.db.models import F

from instagram.models import Post


@shared_task(bind=True, max_retries=3, default_retry_delay=10, ignore_result=True)
def increment_post_view_count(self, post_id: str) -> None:
    """Atomically increment a post's view_count by 1.

    Uses .update() instead of .save() so this never triggers the post_save
    signal (avoiding noisy simple_history snapshot rows on every view).
    """
    Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)
