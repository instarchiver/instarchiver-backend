from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch

from celery.result import EagerResult
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from instagram.models import Story
from instagram.tasks import auto_generate_story_blur_data_urls
from instagram.tasks import generate_story_embedding
from instagram.tasks import increment_story_view_count
from instagram.tasks import moderate_story_content
from instagram.tasks import periodic_generate_story_embeddings
from instagram.tasks import periodic_moderate_story_content
from instagram.tasks import story_generate_blur_data_url
from instagram.tests.factories import StoryFactory


def _make_image_file():
    """Return a minimal SimpleUploadedFile that looks like a JPEG."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile("thumb.jpg", buf.read(), content_type="image/jpeg")


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
        story = StoryFactory(embedding=embedding_val)
        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "already exists" in result.result["message"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_thumbnail(self):
        """Test task returns error when story has no thumbnail file."""
        story = StoryFactory(thumbnail_url="")
        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "thumbnail" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.story.generate_image_embedding")
    def test_success(self, mock_generate_embedding):
        """Test successful embedding generation."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        mock_embedding = [0.2] * 1536
        mock_generate_embedding.return_value = (mock_embedding, 30)

        result = generate_story_embedding.delay(story.story_id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["dimensions"] == 1536  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.story.generate_image_embedding")
    def test_errors_fail_the_task_without_retry(self, mock_generate_embedding):
        """API errors fail the task once; the periodic task requeues it later."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        for error in (ValueError("Empty input"), Exception("openai connection error")):
            mock_generate_embedding.reset_mock()
            mock_generate_embedding.side_effect = error

            result = generate_story_embedding.delay(story.story_id)

            assert isinstance(result, EagerResult)
            assert result.failed()
            assert result.result is error
            mock_generate_embedding.assert_called_once()


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
        """Test that tasks are queued for stories with thumbnail but no embedding."""
        story = StoryFactory(thumbnail_url="", embedding=None)
        story.thumbnail = _make_image_file()
        story.save()

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
        story = StoryFactory(thumbnail_url="", embedding=None)
        story.thumbnail = _make_image_file()
        story.save()

        mock_task_delay.side_effect = Exception("Broker down")

        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["errors"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_stories_with_existing_embeddings_are_skipped(self):
        """Test that stories with existing embeddings are not re-queued."""
        story = StoryFactory(thumbnail_url="", embedding=[0.1] * 1536)
        story.thumbnail = _make_image_file()
        story.save()

        result = periodic_generate_story_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["queued"] == 0


class TestPeriodicStoryTaskErrors(TestCase):
    """DB errors in the periodic story tasks end the task in FAILURE."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_db_error_fails_periodic_tasks(self):
        """Each periodic task ends in FAILURE when the story query breaks."""
        tasks = (
            periodic_generate_story_embeddings,
            auto_generate_story_blur_data_urls,
            periodic_moderate_story_content,
        )
        with patch(
            "instagram.tasks.story.Story.objects.filter",
            side_effect=Exception("DB crash"),
        ):
            for task in tasks:
                result = task.delay()
                assert isinstance(result, EagerResult)
                assert result.failed()


class TestModerateStoryContent(TestCase):
    """Tests for the moderate_story_content Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_story_not_found(self):
        """Test task returns error when story does not exist."""
        result = moderate_story_content.delay("nonexistent-story-id")
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_success(self):
        """Test successful story moderation."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        with patch.object(Story, "moderate_content"):
            result = moderate_story_content.delay(story.story_id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["story_id"] == story.story_id

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_exception_exhausts_retries(self):
        """Test that exceptions trigger retries and the task ultimately fails."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        with patch.object(Story, "moderate_content", side_effect=Exception("API down")):
            result = moderate_story_content.delay(story.story_id)

        assert isinstance(result, EagerResult)
        assert result.failed()


class TestPeriodicModerateStoryContent(TestCase):
    """Tests for the periodic_moderate_story_content Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_stories_to_process(self):
        """Test task returns early when no stories need moderation."""
        Story.objects.all().delete()
        result = periodic_moderate_story_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.moderate_story_content.delay")
    def test_queues_tasks_for_eligible_stories(self, mock_task_delay):
        """Test that tasks are queued for stories with thumbnails but no moderation."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        mock_result = MagicMock()
        mock_result.id = "mod-task-1"
        mock_task_delay.return_value = mock_result

        result = periodic_moderate_story_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_already_moderated_stories_skipped(self):
        """Test that stories with moderated_at set are not re-queued."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.moderated_at = timezone.now()
        story.save()

        result = periodic_moderate_story_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.moderate_story_content.delay")
    def test_error_handling(self, mock_task_delay):
        """Test that individual queuing errors are tracked."""
        story = StoryFactory(thumbnail_url="")
        story.thumbnail = _make_image_file()
        story.save()

        mock_task_delay.side_effect = Exception("Queue full")

        result = periodic_moderate_story_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["errors"] >= 1


class TestIncrementStoryViewCount(TestCase):
    def test_increments_view_count(self):
        story = StoryFactory()
        assert story.view_count == 0

        increment_story_view_count(story.story_id)

        story.refresh_from_db()
        assert story.view_count == 1

    def test_missing_story_is_a_no_op(self):
        increment_story_view_count("does-not-exist")


class TestStoriesWithoutThumbnailAreSkipped(TestCase):
    """Video stories from SaveAPI have no thumbnail until a frame is extracted."""

    def setUp(self):
        Story.objects.all().delete()
        self.story = StoryFactory(
            thumbnail_url="",
            blur_data_url="",
            embedding=None,
            moderated_at=None,
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story_generate_blur_data_url.delay")
    def test_blur_skips_story_without_image(self, mock_delay):
        result = auto_generate_story_blur_data_urls.delay()

        assert result.result["queued"] == 0
        mock_delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.generate_story_embedding.delay")
    def test_embedding_skips_story_without_thumbnail(self, mock_delay):
        result = periodic_generate_story_embeddings.delay()

        assert result.result["queued"] == 0
        mock_delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.moderate_story_content.delay")
    def test_moderation_skips_story_without_thumbnail(self, mock_delay):
        result = periodic_moderate_story_content.delay()

        assert result.result["queued"] == 0
        mock_delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.story.generate_blur_data_url_from_image_url")
    def test_single_blur_task_returns_without_image(self, mock_generate):
        result = story_generate_blur_data_url.delay(self.story.story_id)

        assert result.result["success"] is False
        assert result.result["error"] == "No thumbnail"
        mock_generate.assert_not_called()
