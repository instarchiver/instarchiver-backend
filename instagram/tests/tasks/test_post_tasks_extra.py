"""Additional tests for edge-case/exception paths in instagram/tasks/post.py."""

from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch

from celery.result import EagerResult
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from instagram.models import Post
from instagram.tasks import generate_post_embedding
from instagram.tasks import moderate_post_content
from instagram.tasks import periodic_generate_post_embeddings
from instagram.tasks import periodic_generate_post_media_blur_data_urls
from instagram.tasks import periodic_moderate_post_content
from instagram.tests.factories import PostFactory


class TestPeriodicPostTaskCriticalErrors(TestCase):
    """Tests for the critical-error fallback handlers in periodic post tasks."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_media_blur_data_urls_critical_error(self):
        """Test critical error in periodic_generate_post_media_blur_data_urls."""
        with patch(
            "instagram.tasks.post.PostMedia.objects.filter",
            side_effect=Exception("DB crash"),
        ):
            result = periodic_generate_post_media_blur_data_urls.delay()

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Critical error" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_embeddings_critical_error(self):
        """Test critical error in periodic_generate_post_embeddings."""
        with patch(
            "instagram.tasks.post.Post.objects.filter",
            side_effect=Exception("DB timeout"),
        ):
            result = periodic_generate_post_embeddings.delay()

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Critical error" in result.result["error"]


class TestGeneratePostEmbeddingEdgeCases(TestCase):
    """Tests for exception-handling paths in generate_post_embedding."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_value_error_returns_failure(self):
        """Test that ValueError from generate_embedding returns failure."""
        post = PostFactory(embedding=None, raw_data=None)
        post.thumbnail.name = "thumb.jpg"
        post.save()
        with patch.object(
            post.__class__,
            "generate_embedding",
            side_effect=ValueError("Empty content"),
        ):
            result = generate_post_embedding.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "ValueError" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_non_retryable_exception_returns_failure(self):
        """Test that a non-retryable generic error returns failure."""
        post = PostFactory(embedding=None, raw_data=None)
        post.thumbnail.name = "thumb.jpg"
        post.save()
        with patch.object(
            post.__class__,
            "generate_embedding",
            side_effect=Exception("Permanent error"),
        ):
            result = generate_post_embedding.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert result.result["attempts"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_retryable_network_exception_exhausts_retries(self):
        """Test that a retryable network error exhausts retries and returns failure."""
        post = PostFactory(embedding=None, raw_data=None)
        post.thumbnail.name = "thumb.jpg"
        post.save()
        with patch.object(
            post.__class__,
            "generate_embedding",
            side_effect=Exception("network timeout"),
        ):
            result = generate_post_embedding.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert result.result["attempts"] >= 1


class TestModeratePostContent(TestCase):
    """Tests for the moderate_post_content Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_post_not_found(self):
        """Test task returns error when post does not exist."""
        result = moderate_post_content.delay("nonexistent-post-id")
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_success(self):
        """Test successful post moderation."""
        post = PostFactory(thumbnail_url="", raw_data=None)

        with patch.object(Post, "moderate_content"):
            result = moderate_post_content.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["post_id"] == post.id

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_exception_exhausts_retries(self):
        """Test that exceptions trigger retries and the task ultimately fails."""
        post = PostFactory(thumbnail_url="", raw_data=None)

        with patch.object(Post, "moderate_content", side_effect=Exception("API down")):
            result = moderate_post_content.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.failed()


class TestPeriodicModeratePostContent(TestCase):
    """Tests for the periodic_moderate_post_content Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_posts_to_process(self):
        """Test task returns early when no posts need moderation."""
        Post.objects.all().delete()
        result = periodic_moderate_post_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.moderate_post_content.delay")
    def test_queues_tasks_for_eligible_posts(self, mock_task_delay):
        """Test that tasks are queued for posts with thumbnails but no moderation."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        img = Image.new("RGB", (10, 10))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        post.thumbnail.save("thumb.jpg", buf, save=True)

        mock_result = MagicMock()
        mock_result.id = "mod-task-1"
        mock_task_delay.return_value = mock_result

        result = periodic_moderate_post_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_already_moderated_posts_skipped(self):
        """Test that posts with moderated_at set are not re-queued."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        img = Image.new("RGB", (10, 10))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        post.thumbnail.save("thumb.jpg", buf, save=False)
        post.moderated_at = timezone.now()
        post.save()

        result = periodic_moderate_post_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.moderate_post_content.delay")
    def test_error_handling(self, mock_task_delay):
        """Test that individual queuing errors are tracked."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        img = Image.new("RGB", (10, 10))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        post.thumbnail.save("thumb.jpg", buf, save=True)

        mock_task_delay.side_effect = Exception("Queue full")

        result = periodic_moderate_post_content.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["errors"] >= 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_critical_error(self):
        """Test that DB errors in periodic_moderate_post_content are handled."""
        with patch(
            "instagram.tasks.post.Post.objects.filter",
            side_effect=Exception("DB down"),
        ):
            result = periodic_moderate_post_content.delay()

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Critical error" in result.result["error"]
