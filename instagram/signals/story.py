from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from instagram.models import Story
from instagram.tasks.story import download_story_media_from_url
from instagram.tasks.story import download_story_thumbnail_from_url


@receiver(post_save, sender=Story)
def queue_story_media_download(sender, instance, **kwargs):
    """Queue downloads for a saved story's missing thumbnail and media files."""
    story_id = instance.story_id
    if instance.thumbnail_url and not instance.thumbnail:
        transaction.on_commit(lambda: download_story_thumbnail_from_url.delay(story_id))

    if instance.media_url and not instance.media:
        transaction.on_commit(lambda: download_story_media_from_url.delay(story_id))
