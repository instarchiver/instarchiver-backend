from unittest.mock import patch

from django.test import TestCase

from instagram.models import Story
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import StoryFactory


class TestUserSignal(TestCase):
    """Tests for the user post_save signal."""

    @patch("instagram.signals.user.update_profile_picture_from_url.delay")
    def test_signal_queues_task_when_profile_pic_url_set(self, mock_delay):
        """Test that saving a user with a profile picture URL queues the task."""
        with self.captureOnCommitCallbacks(execute=True):
            user = InstagramUserFactory(
                original_profile_picture_url="https://example.com/pic.jpg",
            )
        mock_delay.assert_called_with(str(user.uuid))

    @patch("instagram.signals.user.update_profile_picture_from_url.delay")
    def test_signal_does_not_queue_when_no_profile_pic_url(self, mock_delay):
        """Test that saving a user without a profile picture URL does not queue task."""
        with self.captureOnCommitCallbacks(execute=True):
            InstagramUserFactory(original_profile_picture_url="")
        mock_delay.assert_not_called()


class TestStorySignal(TestCase):
    """Tests for the story post_save signal (queue_story_media_download)."""

    @patch("instagram.tasks.story.download_story_thumbnail_from_url.delay")
    def test_thumbnail_task_queued_when_url_set(self, mock_delay):
        """Test that thumbnail download task is queued when thumbnail_url is set."""
        with self.captureOnCommitCallbacks(execute=True):
            story = StoryFactory(
                thumbnail_url="https://example.com/thumb.jpg",
                media_url="",
            )
        mock_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.story.download_story_media_from_url.delay")
    def test_media_task_queued_when_url_set(self, mock_delay):
        """Test that media download task is queued when media_url is set."""
        with self.captureOnCommitCallbacks(execute=True):
            story = StoryFactory(
                thumbnail_url="",
                media_url="https://example.com/vid.mp4",
            )
        mock_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.story.download_story_thumbnail_from_url.delay")
    @patch("instagram.tasks.story.download_story_media_from_url.delay")
    def test_no_tasks_queued_when_urls_empty(self, mock_media_delay, mock_thumb_delay):
        """Test that no tasks are queued when both URLs are empty."""
        with self.captureOnCommitCallbacks(execute=True):
            StoryFactory(thumbnail_url="", media_url="")
        mock_thumb_delay.assert_not_called()
        mock_media_delay.assert_not_called()

    @patch("instagram.tasks.story.download_story_thumbnail_from_url.delay")
    def test_no_task_queued_when_thumbnail_already_set(self, mock_delay):
        """Test that no task is queued when the thumbnail file is already populated."""
        story = StoryFactory(thumbnail_url="", media_url="")
        mock_delay.reset_mock()
        # Simulate a previously downloaded thumbnail via queryset update (bypass signal)
        Story.objects.filter(story_id=story.story_id).update(
            thumbnail_url="https://example.com/t.jpg",
            thumbnail="stories/existing_thumb.jpg",
        )
        with self.captureOnCommitCallbacks(execute=True):
            story = Story.objects.get(story_id=story.story_id)
            story.save()
        mock_delay.assert_not_called()
