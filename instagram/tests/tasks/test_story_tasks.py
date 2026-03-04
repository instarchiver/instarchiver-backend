from unittest.mock import MagicMock
from unittest.mock import patch

from celery.result import EagerResult
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings

from instagram.models import Story
from instagram.tasks import (
    generate_story_embedding,
)
from instagram.tasks import (
    generate_story_thumbnail_insight,
)
from instagram.tasks import (
    periodic_generate_story_embeddings,
)
from instagram.tasks import (
    periodic_generate_story_thumbnail_insights,
)
from instagram.tests.factories import StoryFactory


def _make_image_file():
    """Return a minimal SimpleUploadedFile that looks like a JPEG."""
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (10, 10), color="blue")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile("thumb.jpg", buf.read(), content_type="image/jpeg")


class TestGenerateStoryThumbnailInsight(TestCase):
    """Tests for the generate_story_thumbnail_insight Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_story_not_found(self):
        """Test task returns error when story does not exist."""
        result = generate_story_thumbnail_insight.delay("nonexistent_id")
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.signals.story.download_file_from_url")
    def test_no_thumbnail_file(self, mock_download):
        """Test task returns error when story has no thumbnail file."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="")
        result = generate_story_thumbnail_insight.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "thumbnail" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.signals.story.download_file_from_url")
    def test_insight_already_exists(self, mock_download):
        """Test task returns early when insight already exists."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="", thumbnail_insight="")
        # Attach a thumbnail so the task passes the thumbnail check,
        # then set the insight so it hits the "already exists" early return.
        story.thumbnail = _make_image_file()
        story.thumbnail_insight = "Existing insight text"
        story.save()
        result = generate_story_thumbnail_insight.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "already exists" in result.result["message"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.story.get_openai_client")
    @patch("instagram.signals.story.download_file_from_url")
    def test_success(self, mock_download, mock_get_client):
        """Test successful thumbnail insight generation."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="", thumbnail_insight="")
        # Attach a real thumbnail file so the model method works
        story.thumbnail = _make_image_file()
        story.save()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated insight"
        mock_response.usage.total_tokens = 75
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = generate_story_thumbnail_insight.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.signals.story.download_file_from_url")
    def test_value_error_returns_failure(self, mock_download):
        """Test that a ValueError raised by the model method returns a failure result."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="", thumbnail_insight="")
        story.thumbnail = _make_image_file()
        story.save()

        # Patch the model instance method so it raises ValueError directly,
        # which is the path the task's except ValueError handler covers.
        with patch.object(
            story.__class__,
            "generate_thumbnail_insight",
            side_effect=ValueError("Missing thumbnail"),
        ):
            result = generate_story_thumbnail_insight.delay(story.story_id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "ValueError" in result.result["error"]


class TestPeriodicGenerateStoryThumbnailInsights(TestCase):
    """Tests for the periodic_generate_story_thumbnail_insights task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_stories_to_process(self):
        """Test task returns early when no stories need processing."""
        # Ensure database is empty for this test
        Story.objects.all().delete()
        result = periodic_generate_story_thumbnail_insights.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.generate_story_thumbnail_insight.delay")
    @patch("instagram.signals.story.download_file_from_url")
    def test_queues_tasks_for_eligible_stories(self, mock_download, mock_task_delay):
        """Test that tasks are queued for stories with thumbnails but no insight."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="", thumbnail_insight="")
        story.thumbnail = _make_image_file()
        story.save()

        mock_result = MagicMock()
        mock_result.id = "task-999"
        mock_task_delay.return_value = mock_result

        result = periodic_generate_story_thumbnail_insights.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.generate_story_thumbnail_insight.delay")
    @patch("instagram.signals.story.download_file_from_url")
    def test_error_handling(self, mock_download, mock_task_delay):
        """Test that individual queuing errors are tracked."""
        mock_download.return_value = (None, None)
        story = StoryFactory(thumbnail_url="", thumbnail_insight="")
        story.thumbnail = _make_image_file()
        story.save()

        mock_task_delay.side_effect = Exception("Queue full")

        result = periodic_generate_story_thumbnail_insights.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["errors"] >= 1


class TestGenerateStoryEmbedding(TestCase):
    """Tests for the generate_story_embedding Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_story_not_found(self):
        """Test task returns error when story does not exist."""
        result = generate_story_embedding.delay("nonexistent_story")
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_embedding_already_exists(self):
        """Test task returns early when embedding already exists."""
        embedding_val = [0.1] * 1536
        story = StoryFactory(
            thumbnail_insight="Some insight",
            embedding=embedding_val,
        )
        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "already exists" in result.result["message"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_thumbnail_insight(self):
        """Test task returns error when story has no thumbnail_insight."""
        story = StoryFactory(thumbnail_insight="")
        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "thumbnail_insight" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("core.utils.openai.generate_text_embedding")
    def test_success(self, mock_generate_embedding):
        """Test successful embedding generation."""
        story = StoryFactory(thumbnail_insight="Rich description of photo")
        mock_embedding = [0.2] * 1536
        mock_generate_embedding.return_value = (mock_embedding, 30)

        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["dimensions"] == 1536  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("core.utils.openai.generate_text_embedding")
    def test_value_error_returns_failure(self, mock_generate_embedding):
        """Test that a ValueError returns a failure result."""
        story = StoryFactory(thumbnail_insight="Some insight")
        mock_generate_embedding.side_effect = ValueError("Empty input")

        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "ValueError" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("core.utils.openai.generate_text_embedding")
    def test_returns_none_embedding(self, mock_generate_embedding):
        """Test that a None embedding result is handled gracefully."""
        story = StoryFactory(thumbnail_insight="Some insight")
        mock_generate_embedding.return_value = (None, 0)

        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        # When generate_embedding returns None, the task returns failure
        assert result.result["success"] is False


class TestPeriodicGenerateStoryEmbeddings(TestCase):
    """Tests for the periodic_generate_story_embeddings task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_stories_to_process(self):
        """Test task returns early when no stories need embeddings."""
        Story.objects.all().delete()
        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_queues_tasks_for_eligible_stories(self, mock_task_delay):
        """Test that tasks are queued for stories with insight but no embedding."""
        StoryFactory(thumbnail_insight="Has insight", embedding=None)

        mock_result = MagicMock()
        mock_result.id = "embed-task-1"
        mock_task_delay.return_value = mock_result

        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_error_handling(self, mock_task_delay):
        """Test that queuing errors are tracked correctly."""
        StoryFactory(thumbnail_insight="Has insight", embedding=None)
        mock_task_delay.side_effect = Exception("Broker down")

        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["errors"] >= 1
        assert result.result["error_details"] is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_stories_with_existing_embeddings_are_skipped(self):
        """Test that stories with existing embeddings are not re-queued."""
        # Story with insight AND existing embedding — should be skipped
        StoryFactory(thumbnail_insight="Has insight", embedding=[0.1] * 1536)
        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["queued"] == 0
