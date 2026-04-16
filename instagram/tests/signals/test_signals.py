from unittest.mock import patch

from django.test import TestCase

from instagram.models import PostMedia
from instagram.models import Story
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory
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


class TestPostSignal(TestCase):
    """Tests for the post post_save signal (post_post_save)."""

    @patch("instagram.signals.post.download_post_thumbnail_from_url.delay")
    def test_thumbnail_task_queued_when_url_set(self, mock_delay):
        """Test that thumbnail download task is queued when thumbnail_url is set."""
        with self.captureOnCommitCallbacks(execute=True):
            post = PostFactory(
                thumbnail_url="https://example.com/thumb.jpg",
                raw_data=None,
            )
        mock_delay.assert_called_with(post.id)

    @patch("instagram.signals.post.download_post_thumbnail_from_url.delay")
    def test_post_processing_queued_when_raw_data_set(self, mock_delay):
        """Test that post type processing runs when raw_data is set."""
        raw_data = {
            "id": "media_123",
            "image_versions2": {
                "candidates": [{"url": "https://example.com/img.jpg"}],
            },
        }
        with self.captureOnCommitCallbacks(execute=True):
            post = PostFactory(raw_data=raw_data)
        post.refresh_from_db()
        # Post media should have been created via signal
        assert PostMedia.objects.filter(post=post).exists()


class TestPostMediaSignal(TestCase):
    """Tests for the post media post_save signal (post_media_post_save)."""

    @patch("instagram.signals.post_media.download_post_media_thumbnail_from_url.delay")
    @patch("instagram.signals.post_media.post_media_generate_blur_data_url.delay")
    @patch("instagram.signals.post_media.download_post_media_from_url.delay")
    def test_tasks_queued_on_create(
        self,
        mock_media_delay,
        mock_blur_delay,
        mock_thumb_delay,
    ):
        """Test that download and blur tasks are queued on PostMedia creation."""
        # Use raw_data=None to avoid post-type processing in the parent signal
        parent_post = PostFactory(raw_data=None)
        with self.captureOnCommitCallbacks(execute=True):
            post_media = PostMediaFactory(
                post=parent_post,
                thumbnail_url="https://example.com/thumb.jpg",
                media_url="https://example.com/media.mp4",
            )
        mock_thumb_delay.assert_called_with(post_media.id)
        mock_media_delay.assert_called_with(post_media.id)
        mock_blur_delay.assert_called_with(post_media.id)
