import base64
from io import BytesIO
from unittest.mock import Mock
from unittest.mock import patch

from celery.result import EagerResult
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings
from PIL import Image

from instagram.models import Story
from instagram.tasks import auto_generate_story_blur_data_urls
from instagram.tasks import story_generate_blur_data_url
from instagram.tests.factories import StoryFactory


def _story_with_thumbnail():
    """Return a story with a stored 200x100 JPEG thumbnail and no blur."""
    buffer = BytesIO()
    Image.new("RGB", (200, 100), color="red").save(buffer, format="JPEG")
    story = StoryFactory(blur_data_url="")
    story.thumbnail.save("thumb.jpg", ContentFile(buffer.getvalue()), save=False)
    Story.objects.filter(pk=story.pk).update(thumbnail=story.thumbnail.name)
    return story


def _queueable_story(**kwargs):
    """Return a story whose thumbnail name is set, for the periodic tests."""
    story = StoryFactory(**kwargs)
    Story.objects.filter(pk=story.pk).update(thumbnail="stories/a.jpg")
    return story


class TestStoryGenerateBlurDataUrl(TestCase):
    """Tests for the story_generate_blur_data_url Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story.generate_blur_data_url_from_image")
    def test_story_generate_blur_data_url_success(
        self,
        mock_generate_blur,
    ):
        """Test successful blur data URL generation and saving."""
        # Create a test story
        story = _story_with_thumbnail()

        # Mock the utility function
        mock_generate_blur.return_value = "base64encodedstring"

        # Execute the task
        result = story_generate_blur_data_url.delay(story.story_id)

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["story_id"] == story.story_id

        # Verify the blur_data_url was saved to the model
        story.refresh_from_db()
        assert story.blur_data_url == "base64encodedstring"

        # Verify the utility function was called with correct URL
        mock_generate_blur.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_story_generate_blur_data_url_story_not_found(self):
        """Test handling of non-existent story."""

        # Execute the task with non-existent story ID
        result = story_generate_blur_data_url.delay("nonexistent_story_id")

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story.generate_blur_data_url_from_image")
    def test_story_generate_blur_data_url_saves_to_model(
        self,
        mock_generate_blur,
    ):
        """Test that blur_data_url is correctly saved to the Story model."""
        # Create a test story
        story = _story_with_thumbnail()

        # Mock the utility function with a specific value
        test_blur_data = "test_base64_encoded_blur_data"
        mock_generate_blur.return_value = test_blur_data

        # Execute the task
        story_generate_blur_data_url.delay(story.story_id)

        # Verify the blur_data_url was saved
        story.refresh_from_db()
        assert story.blur_data_url == test_blur_data

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story.generate_blur_data_url_from_image")
    def test_story_generate_blur_data_url_error_fails_without_retry(
        self,
        mock_generate_blur,
    ):
        """An error fails the task once and leaves blur_data_url empty."""
        story = _story_with_thumbnail()
        mock_generate_blur.side_effect = Exception("Network timeout")

        result = story_generate_blur_data_url.delay(story.story_id)

        assert isinstance(result, EagerResult)
        assert result.failed()
        mock_generate_blur.assert_called_once()
        story.refresh_from_db()
        assert story.blur_data_url == ""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story.generate_blur_data_url_from_image")
    def test_story_generate_blur_data_url_keeps_concurrent_file_update(
        self,
        mock_generate_blur,
    ):
        """A media file saved while the blur runs is not overwritten."""
        story = _story_with_thumbnail()

        def download_finishes_meanwhile(_img):
            Story.objects.filter(pk=story.pk).update(media="stories/a.mp4")
            return "data:image/jpeg;base64,abc"

        mock_generate_blur.side_effect = download_finishes_meanwhile

        story_generate_blur_data_url.delay(story.story_id)

        story.refresh_from_db()
        assert story.media.name == "stories/a.mp4"
        assert story.blur_data_url == "data:image/jpeg;base64,abc"


class TestAutoGenerateStoryBlurDataUrls(TestCase):
    """Tests for the auto_generate_story_blur_data_urls Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_auto_generate_story_blur_data_urls_success(
        self,
        mock_task_delay,
    ):
        """Test successful queuing of blur data URL generation tasks."""
        # Create stories without blur_data_url
        _queueable_story(blur_data_url="")
        _queueable_story(blur_data_url="")
        _queueable_story(blur_data_url="")

        # Create a story with blur_data_url (should be skipped)
        StoryFactory(blur_data_url="existing_blur_data")

        # Mock the task delay to return a mock result
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = auto_generate_story_blur_data_urls.delay()

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

        # Verify story_generate_blur_data_url was called for each story
        assert mock_task_delay.call_count == 3  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_generate_story_blur_data_urls_no_stories(self):
        """Test when no stories need processing."""
        # Create only stories with blur_data_url
        StoryFactory(blur_data_url="existing_blur_data_1")
        StoryFactory(blur_data_url="existing_blur_data_2")

        # Execute the task
        result = auto_generate_story_blur_data_urls.delay()

        # Verify the task returns success with no stories processed
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_auto_generate_story_blur_data_urls_only_empty_blur_data(
        self,
        mock_task_delay,
    ):
        """Test that only stories without blur_data_url are processed."""
        # Create stories with and without blur_data_url
        story_without_blur = _queueable_story(blur_data_url="")
        StoryFactory(blur_data_url="has_blur_data")

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = auto_generate_story_blur_data_urls.delay()

        # Verify only one story was queued
        assert result.result["total"] == 1
        assert result.result["queued"] == 1

        # Verify the correct story was queued
        mock_task_delay.assert_called_once_with(story_without_blur.story_id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_auto_generate_story_blur_data_urls_error_handling(
        self,
        mock_task_delay,
    ):
        """Test error handling when queuing tasks fails."""
        # Create stories without blur_data_url
        _queueable_story(blur_data_url="")
        _queueable_story(blur_data_url="")

        # Mock the task delay to raise an exception for the first story
        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        # Execute the task
        result = auto_generate_story_blur_data_urls.delay()

        # Verify the task completed with errors
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_generate_story_blur_data_urls_empty_database(self):
        """Test when there are no stories in the database."""
        # Ensure no stories exist
        Story.objects.all().delete()

        # Execute the task
        result = auto_generate_story_blur_data_urls.delay()

        # Verify the task returns success with no stories
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_story_with_only_thumbnail_url_is_not_queued(self, mock_task_delay):
        """A story whose thumbnail was never stored is skipped."""
        StoryFactory(blur_data_url="")

        result = auto_generate_story_blur_data_urls.delay()

        assert result.result["queued"] == 0
        mock_task_delay.assert_not_called()


class TestStoryBlurFromStoredFile(TestCase):
    """The blur is built from the stored thumbnail, not a URL."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_blur_is_jpeg_from_stored_file(self):
        story = _story_with_thumbnail()

        story_generate_blur_data_url.delay(story.story_id)

        story.refresh_from_db()
        blur = Image.open(BytesIO(base64.b64decode(story.blur_data_url)))
        assert blur.format == "JPEG"
        assert blur.size == (4, 2)
