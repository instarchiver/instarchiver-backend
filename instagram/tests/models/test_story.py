from io import BytesIO
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from instagram.models.mixins import InstagramModerationMixin
from instagram.tests.factories import StoryFactory


class TestStoryModel(TestCase):
    """Tests for the Story model methods."""

    # Blur Data URL Task Tests
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_queues_task(self, mock_task_delay):
        """Test that generate_blur_data_url_task queues a Celery task."""
        story = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        story.generate_blur_data_url_task()

        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_passes_story_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_blur_data_url_task passes correct story_id."""
        story = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        story.generate_blur_data_url_task()

        mock_task_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        story1 = StoryFactory()
        story2 = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        story1.generate_blur_data_url_task()
        story2.generate_blur_data_url_task()

        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(story1.story_id)
        mock_task_delay.assert_any_call(story2.story_id)

    # Embedding Task Tests
    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_queues_task(self, mock_task_delay):
        """Test that generate_embedding_task queues a Celery task."""
        story = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        story.generate_embedding_task()

        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_passes_story_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_embedding_task passes correct story_id."""
        story = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        story.generate_embedding_task()

        mock_task_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        story1 = StoryFactory()
        story2 = StoryFactory()

        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        story1.generate_embedding_task()
        story2.generate_embedding_task()

        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(story1.story_id)
        mock_task_delay.assert_any_call(story2.story_id)

    # Embedding Generation Tests
    def _create_test_image(self):
        """Helper method to create a test image file."""
        image = Image.new("RGB", (100, 100), color="red")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        return SimpleUploadedFile(
            "test_thumbnail.jpg",
            buffer.getvalue(),
            content_type="image/jpeg",
        )

    def test_generate_embedding_raises_error_without_thumbnail(self):
        """Test that generate_embedding raises ValueError without thumbnail."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = None
        story.save()

        with pytest.raises(ValueError, match="Thumbnail file does not exist"):
            story.generate_embedding()

    @patch("instagram.models.story.generate_image_embedding")
    def test_generate_embedding_success(self, mock_generate_embedding):
        """Test successful embedding generation."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_embedding = [0.1] * 1536
        mock_token_usage = 50
        mock_generate_embedding.return_value = (mock_embedding, mock_token_usage)

        result = story.generate_embedding()

        story.refresh_from_db()
        assert list(story.embedding) == mock_embedding
        assert story.embedding_token_usage == 50  # noqa: PLR2004
        assert result == mock_embedding

        mock_generate_embedding.assert_called_once()

    @patch("instagram.models.story.generate_image_embedding")
    def test_generate_embedding_handles_value_error(self, mock_generate_embedding):
        """Test that generate_embedding re-raises ValueError."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_generate_embedding.side_effect = ValueError("Invalid input")

        with pytest.raises(ValueError, match="Invalid input"):
            story.generate_embedding()

    @patch("instagram.models.story.generate_image_embedding")
    def test_generate_embedding_handles_exception(self, mock_generate_embedding):
        """Test that generate_embedding returns None on general exceptions."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_generate_embedding.side_effect = Exception("API Error")

        result = story.generate_embedding()

        assert result is None

    # Moderate Content Tests
    def test_moderate_content_raises_error_without_thumbnail(self):
        """Test that moderate_content raises ValueError when no thumbnail exists."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = None
        story.save()

        with pytest.raises(ValueError, match="Thumbnail is required"):
            story.moderate_content()

    @patch("instagram.models.story.moderate_image_content")
    def test_moderate_content_success_flagged(self, mock_moderate):
        """Test moderate_content saves fields when content is flagged."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_moderate.return_value = {
            "flagged": True,
            "categories": {"violence": True},
        }

        story.moderate_content()

        story.refresh_from_db()
        assert story.is_flagged is True
        assert story.moderation_result == {
            "flagged": True,
            "categories": {"violence": True},
        }
        assert story.moderated_at is not None

    @patch("instagram.models.story.moderate_image_content")
    def test_moderate_content_success_not_flagged(self, mock_moderate):
        """Test moderate_content saves is_flagged=False when content is clean."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_moderate.return_value = {"is_flagged": False, "categories": {}}

        story.moderate_content()

        story.refresh_from_db()
        assert story.is_flagged is False
        assert story.moderated_at is not None


class TestInstagramModerationMixin(TestCase):
    """Tests for InstagramModerationMixin methods."""

    def test_moderate_content_raises_not_implemented(self):
        """Test that the mixin's moderate_content raises NotImplementedError."""
        story = StoryFactory()
        with pytest.raises(NotImplementedError, match="Subclasses must implement"):
            InstagramModerationMixin.moderate_content(story)

    def test_str_returns_expected_format(self):
        """Test that the mixin's __str__ returns flagged/moderated_at info."""
        story = StoryFactory()
        result = InstagramModerationMixin.__str__(story)
        assert "Flagged:" in result
        assert "Moderated At:" in result
