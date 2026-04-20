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
from instagram.tasks import download_post_media_from_url
from instagram.tasks import download_post_media_thumbnail_from_url
from instagram.tasks import download_post_thumbnail_from_url
from instagram.tasks import generate_post_embedding
from instagram.tasks import moderate_post_content
from instagram.tasks import periodic_generate_post_blur_data_urls
from instagram.tasks import periodic_generate_post_embeddings
from instagram.tasks import periodic_generate_post_media_blur_data_urls
from instagram.tasks import periodic_moderate_post_content
from instagram.tasks.post import _determine_file_extension
from instagram.tasks.post import _get_file_hash
from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory


class TestPeriodicPostTaskCriticalErrors(TestCase):
    """Tests for the critical-error fallback handlers in periodic post tasks."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_blur_data_urls_critical_error(self):
        """Test critical error in periodic_generate_post_blur_data_urls."""
        with patch(
            "instagram.tasks.post.Post.objects.filter",
            side_effect=Exception("DB connection lost"),
        ):
            result = periodic_generate_post_blur_data_urls.delay()

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Critical error" in result.result["error"]

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


class TestGetFileHashEdgeCases(TestCase):
    """Tests for the _get_file_hash helper function."""

    def test_get_file_hash_returns_none_on_oserror(self):
        """Test that _get_file_hash returns None when file cannot be opened."""
        mock_file_field = MagicMock()
        mock_file_field.__bool__ = MagicMock(return_value=True)
        mock_file_field.open.side_effect = OSError("File not found")

        result = _get_file_hash(mock_file_field)
        assert result is None

    def test_get_file_hash_returns_none_when_field_empty(self):
        """Test that _get_file_hash returns None when file field is falsy."""
        result = _get_file_hash(None)
        assert result is None


class TestDetermineFileExtension(TestCase):
    """Tests for the _determine_file_extension helper function."""

    def test_video_content_type_returns_mp4(self):
        """Test that video content type returns mp4."""
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "video/mp4"}
        result = _determine_file_extension(mock_response, "https://example.com/v")
        assert result == "mp4"

    def test_image_content_type_returns_jpg(self):
        """Test that image content type returns jpg."""
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "image/jpeg"}
        result = _determine_file_extension(mock_response, "https://example.com/i")
        assert result == "jpg"

    def test_unknown_content_type_falls_back_to_url_extension(self):
        """Test that unknown content type falls back to URL extension."""
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/octet-stream"}
        result = _determine_file_extension(
            mock_response,
            "https://example.com/file.webm",
        )
        assert result == "webm"


class TestDownloadPostThumbnailEdgeCases(TestCase):
    """Tests for edge cases in download_post_thumbnail_from_url."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_thumbnail_url_returns_error(self):
        """Test that a post without a thumbnail_url returns an error."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        result = download_post_thumbnail_from_url.delay(post.id)

        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "No thumbnail URL" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.requests.get")
    def test_image_dimension_exception_handled(self, mock_get):
        """Test that failure to parse image dimensions is handled gracefully."""
        post = PostFactory(thumbnail_url="https://example.com/thumb.jpg", raw_data=None)

        # Provide valid bytes for response so download succeeds
        img = Image.new("RGB", (5, 5))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        img_bytes = buf.getvalue()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = img_bytes
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Patch PIL to fail so dimension exception is triggered
        with patch("instagram.tasks.post.Image.open", side_effect=OSError("Bad image")):
            result = download_post_thumbnail_from_url.delay(post.id)

        assert isinstance(result, EagerResult)
        # Task completes (with None width/height) but still saves
        assert result.result["success"] is True

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.requests.get")
    def test_non_retryable_exception_returns_failure(self, mock_get):
        """Test that a permanent (non-retryable) exception returns failure."""
        post = PostFactory(thumbnail_url="https://example.com/thumb.jpg", raw_data=None)
        mock_get.side_effect = RuntimeError("Permanent failure")

        result = download_post_thumbnail_from_url.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Permanent error" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.requests.get")
    def test_oserror_reading_existing_thumbnail_logged(self, mock_get):
        """Test that OSError reading existing thumbnail is handled gracefully."""
        post = PostFactory(thumbnail_url="https://example.com/t.jpg", raw_data=None)
        # Give the post an existing thumbnail with a mocked file
        mock_thumbnail = MagicMock()
        mock_thumbnail.__bool__ = MagicMock(return_value=True)
        mock_thumbnail.open.side_effect = OSError("File missing on disk")
        post.thumbnail = mock_thumbnail

        # Provide a valid image response so the download itself succeeds
        img = Image.new("RGB", (5, 5))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = buf.getvalue()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = download_post_thumbnail_from_url.delay(post.id)
        assert isinstance(result, EagerResult)
        # Even with OSError reading existing, task should proceed and succeed
        assert result.result["success"] is True


class TestDownloadPostMediaThumbnailEdgeCases(TestCase):
    """Tests for edge cases in download_post_media_thumbnail_from_url."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post._download_file_from_url")
    def test_image_dimension_exception_handled(self, mock_download):
        """Test that failure to parse image dimensions is handled gracefully."""
        post_media = PostMediaFactory(thumbnail_url="https://example.com/t.jpg")

        img = Image.new("RGB", (5, 5))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        mock_download.return_value = buf.getvalue()

        with patch("instagram.tasks.post.Image.open", side_effect=OSError("Bad image")):
            result = download_post_media_thumbnail_from_url.delay(post_media.id)

        assert isinstance(result, EagerResult)
        # Task still saves image with width/height as None
        assert result.result["success"] is True

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post._download_file_from_url")
    def test_non_retryable_exception_returns_failure(self, mock_download):
        """Test that a permanent error returns failure."""
        post_media = PostMediaFactory(thumbnail_url="https://example.com/t.jpg")
        mock_download.side_effect = RuntimeError("Permanent media failure")

        result = download_post_media_thumbnail_from_url.delay(post_media.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Permanent error" in result.result["error"]


class TestDownloadPostMediaFromUrlEdgeCases(TestCase):
    """Tests for edge cases in download_post_media_from_url."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.requests.get")
    def test_non_retryable_exception_returns_failure(self, mock_get):
        """Test permanent error returns failure in download_post_media_from_url."""
        post_media = PostMediaFactory(media_url="https://example.com/m.mp4")
        # RuntimeError is not caught by (RequestException, OSError) → goes to
        # the non-retryable `except Exception` block
        mock_get.side_effect = RuntimeError("Permanent media failure")

        result = download_post_media_from_url.delay(post_media.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Permanent error" in result.result["error"]


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
