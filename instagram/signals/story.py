import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from instagram.models import Story

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Story)
def queue_story_media_download(sender, instance, **kwargs):
    """Queue background tasks to download Story media files after save."""
    if instance.thumbnail_url and not instance.thumbnail:
        transaction.on_commit(instance.queue_thumbnail_download)

    if instance.media_url and not instance.media:
        transaction.on_commit(instance.queue_media_download)
