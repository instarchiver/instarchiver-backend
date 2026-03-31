from io import BytesIO
from unittest.mock import MagicMock
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
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_blur_data_url_task()

        # Verify the task was queued
        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_passes_story_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_blur_data_url_task passes correct story_id."""
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_blur_data_url_task()

        # Verify the task was called with the correct story_id
        mock_task_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        # Create test stories
        story1 = StoryFactory()
        story2 = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method on both stories
        story1.generate_blur_data_url_task()
        story2.generate_blur_data_url_task()

        # Verify the task was queued twice with different story_ids
        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(story1.story_id)
        mock_task_delay.assert_any_call(story2.story_id)

    # Thumbnail Insight Task Tests
    @patch("instagram.tasks.generate_story_thumbnail_insight.delay")
    def test_generate_thumbnail_insight_task_queues_task(self, mock_task_delay):
        """Test that generate_thumbnail_insight_task queues a Celery task."""
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-456"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_thumbnail_insight_task()

        # Verify the task was queued
        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.generate_story_thumbnail_insight.delay")
    def test_generate_thumbnail_insight_task_passes_story_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_thumbnail_insight_task passes correct story_id."""
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-456"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_thumbnail_insight_task()

        # Verify the task was called with the correct story_id
        mock_task_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.generate_story_thumbnail_insight.delay")
    def test_generate_thumbnail_insight_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        # Create test stories
        story1 = StoryFactory()
        story2 = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-456"
        mock_task_delay.return_value = mock_result

        # Call the method on both stories
        story1.generate_thumbnail_insight_task()
        story2.generate_thumbnail_insight_task()

        # Verify the task was queued twice with different story_ids
        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(story1.story_id)
        mock_task_delay.assert_any_call(story2.story_id)

    # Embedding Task Tests
    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_queues_task(self, mock_task_delay):
        """Test that generate_embedding_task queues a Celery task."""
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_embedding_task()

        # Verify the task was queued
        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_passes_story_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_embedding_task passes correct story_id."""
        # Create a test story
        story = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        # Call the method
        story.generate_embedding_task()

        # Verify the task was called with the correct story_id
        mock_task_delay.assert_called_once_with(story.story_id)

    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_generate_embedding_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        # Create test stories
        story1 = StoryFactory()
        story2 = StoryFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-789"
        mock_task_delay.return_value = mock_result

        # Call the method on both stories
        story1.generate_embedding_task()
        story2.generate_embedding_task()

        # Verify the task was queued twice with different story_ids
        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(story1.story_id)
        mock_task_delay.assert_any_call(story2.story_id)

    # Thumbnail Insight Generation Tests
    def _create_test_image(self):
        """Helper method to create a test image file."""
        # Create a simple test image
        image = Image.new("RGB", (100, 100), color="red")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        return SimpleUploadedFile(
            "test_thumbnail.jpg",
            buffer.getvalue(),
            content_type="image/jpeg",
        )

    @patch("instagram.signals.story.download_file_from_url")
    def test_generate_thumbnail_insight_raises_error_without_thumbnail(
        self,
        mock_download,
    ):
        """Test that generate_thumbnail_insight raises ValueError without thumbnail."""
        # Mock download to return None so signal doesn't download files
        mock_download.return_value = (None, None)

        # Create story with thumbnail_url but prevent actual download
        story = StoryFactory(thumbnail_url="")

        # Manually clear the thumbnail field
        story.thumbnail = None
        story.save()

        # Attempt to generate insight should raise ValueError
        with pytest.raises(ValueError, match="Thumbnail file does not exist"):
            story.generate_thumbnail_insight()

    @patch("instagram.models.story.get_openai_client")
    @patch("instagram.signals.story.download_file_from_url")
    def test_generate_thumbnail_insight_success(
        self,
        mock_download,
        mock_get_client,
    ):
        """Test successful thumbnail insight generation."""
        # Mock download to return None so we can set thumbnail manually
        mock_download.return_value = (None, None)

        # Create story
        story = StoryFactory(thumbnail_url="")

        # Manually set the thumbnail
        story.thumbnail = self._create_test_image()
        story.save()

        # Mock OpenAI client response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test insight content"
        mock_response.usage.total_tokens = 150
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Generate insight
        story.generate_thumbnail_insight()

        # Verify the insight was saved
        story.refresh_from_db()
        assert story.thumbnail_insight == "Test insight content"
        assert story.thumbnail_insight_token_usage == 150  # noqa: PLR2004

        # Verify OpenAI API was called
        mock_client.chat.completions.create.assert_called_once()

    @patch("instagram.models.story.get_openai_client")
    @patch("instagram.signals.story.download_file_from_url")
    def test_generate_thumbnail_insight_handles_exception(
        self,
        mock_download,
        mock_get_client,
    ):
        """Test that generate_thumbnail_insight handles exceptions gracefully."""
        # Mock download to return None so we can set thumbnail manually
        mock_download.return_value = (None, None)

        # Create story
        story = StoryFactory(thumbnail_url="")

        # Manually set the thumbnail
        story.thumbnail = self._create_test_image()
        story.save()

        # Mock OpenAI client to raise exception
        mock_get_client.side_effect = Exception("API Error")

        # Generate insight should return empty string
        result = story.generate_thumbnail_insight()

        # Verify empty string returned
        assert result == ""

    # Embedding Generation Tests
    def test_generate_embedding_raises_error_without_insight(self):
        """Test that generate_embedding raises ValueError without thumbnail_insight."""
        # Create story without thumbnail_insight
        story = StoryFactory(thumbnail_insight="")

        # Attempt to generate embedding should raise ValueError
        with pytest.raises(ValueError, match="Thumbnail insight is not available"):
            story.generate_embedding()

    @patch("core.utils.openai.generate_text_embedding")
    def test_generate_embedding_success(self, mock_generate_embedding):
        """Test successful embedding generation."""
        # Create story with thumbnail_insight
        story = StoryFactory(thumbnail_insight="Test thumbnail insight for embedding")

        # Mock embedding generation
        mock_embedding = [0.1] * 1536  # 1536-dimensional vector
        mock_token_usage = 50
        mock_generate_embedding.return_value = (mock_embedding, mock_token_usage)

        # Generate embedding
        result = story.generate_embedding()

        # Verify the embedding was saved
        story.refresh_from_db()
        # Convert to list for comparison (pgvector returns numpy arrays)
        assert list(story.embedding) == mock_embedding
        assert story.embedding_token_usage == 50  # noqa: PLR2004
        assert result == mock_embedding

        # Verify embedding function was called with correct text
        mock_generate_embedding.assert_called_once_with(
            "Test thumbnail insight for embedding",
        )

    @patch("core.utils.openai.generate_text_embedding")
    def test_generate_embedding_handles_value_error(self, mock_generate_embedding):
        """Test that generate_embedding raises ValueError on bad input."""
        # Create story with thumbnail_insight
        story = StoryFactory(thumbnail_insight="Test insight")

        # Mock embedding generation to raise ValueError
        mock_generate_embedding.side_effect = ValueError("Invalid input")

        # Generate embedding should raise ValueError
        with pytest.raises(ValueError, match="Invalid input"):
            story.generate_embedding()

    @patch("core.utils.openai.generate_text_embedding")
    def test_generate_embedding_handles_exception(self, mock_generate_embedding):
        """Test that generate_embedding handles exceptions gracefully."""
        # Create story with thumbnail_insight
        story = StoryFactory(thumbnail_insight="Test insight")

        # Mock embedding generation to raise exception
        mock_generate_embedding.side_effect = Exception("API Error")

        # Generate embedding should return None
        result = story.generate_embedding()

        # Verify None returned
        assert result is None

    # Moderate Content Tests
    @patch("instagram.signals.story.download_file_from_url")
    def test_moderate_content_raises_error_without_thumbnail(self, mock_download):
        """Test that moderate_content raises ValueError when no thumbnail exists."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = None
        story.save()

        with pytest.raises(ValueError, match="Thumbnail is required"):
            story.moderate_content()

    @patch("instagram.models.story.moderate_image_content")
    @patch("instagram.signals.story.download_file_from_url")
    def test_moderate_content_success_flagged(self, mock_download, mock_moderate):
        """Test moderate_content saves fields when content is flagged."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = self._create_test_image()
        story.save()

        mock_moderate.return_value = {
            "is_flagged": True,
            "categories": {"violence": True},
        }

        story.moderate_content()

        story.refresh_from_db()
        assert story.is_flagged is True
        assert story.moderation_result == {
            "is_flagged": True,
            "categories": {"violence": True},
        }
        assert story.moderated_at is not None

    @patch("instagram.models.story.moderate_image_content")
    @patch("instagram.signals.story.download_file_from_url")
    def test_moderate_content_success_not_flagged(self, mock_download, mock_moderate):
        """Test moderate_content saves is_flagged=False when content is clean."""
        mock_download.return_value = (None, None)
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
