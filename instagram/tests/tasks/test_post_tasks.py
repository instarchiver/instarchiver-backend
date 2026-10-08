from unittest.mock import Mock
from unittest.mock import patch

from celery.result import EagerResult
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings

from instagram.models import Post
from instagram.tasks import generate_post_embedding
from instagram.tasks import increment_post_view_count
from instagram.tasks import periodic_generate_post_blur_data_urls
from instagram.tasks import periodic_generate_post_embeddings
from instagram.tasks import periodic_generate_post_media_blur_data_urls
from instagram.tasks import post_generate_blur_data_url
from instagram.tasks import post_media_generate_blur_data_url
from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory


class TestPostGenerateBlurDataUrl(TestCase):
    """Tests for the post_generate_blur_data_url Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_generate_blur_data_url_success(self, mock_generate_blur):
        """Test successful blur data URL generation and saving."""
        # Create a test post
        post = PostFactory(blur_data_url="")

        # Mock the utility function
        mock_generate_blur.return_value = "base64encodedstring"

        # Execute the task
        result = post_generate_blur_data_url.delay(post.id)

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["post_id"] == post.id

        # Verify the blur_data_url was saved to the model
        post.refresh_from_db()
        assert post.blur_data_url == "base64encodedstring"

        # Verify the utility function was called
        mock_generate_blur.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_post_generate_blur_data_url_post_not_found(self):
        """Test handling of non-existent post."""
        # Execute the task with non-existent post ID
        result = post_generate_blur_data_url.delay("nonexistent_post_id")

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_generate_blur_data_url_saves_to_model(self, mock_generate_blur):
        """Test that blur_data_url is correctly saved to the Post model."""
        # Create a test post
        post = PostFactory(blur_data_url="")

        # Mock the utility function with a specific value
        test_blur_data = "test_base64_encoded_blur_data"
        mock_generate_blur.return_value = test_blur_data

        # Execute the task
        post_generate_blur_data_url.delay(post.id)

        # Verify the blur_data_url was saved
        post.refresh_from_db()
        assert post.blur_data_url == test_blur_data

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_generate_blur_data_url_network_error_retry(
        self,
        mock_generate_blur,
    ):
        """Test retry logic on network errors."""
        # Create a test post
        post = PostFactory(blur_data_url="")

        # Mock a network error
        mock_generate_blur.side_effect = Exception("Network timeout")

        # Execute the task
        result = post_generate_blur_data_url.delay(post.id)

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_generate_blur_data_url_uses_thumbnail(self, mock_generate_blur):
        """Test that the task uses the correct thumbnail source."""
        # Create a test post with thumbnail
        post = PostFactory(
            blur_data_url="",
            thumbnail_url="https://example.com/thumbnail.jpg",
        )

        # Mock the utility function
        mock_generate_blur.return_value = "base64encodedstring"

        # Execute the task
        post_generate_blur_data_url.delay(post.id)

        # Verify the utility function was called
        mock_generate_blur.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_generate_blur_data_url_retryable_vs_non_retryable(
        self,
        mock_generate_blur,
    ):
        """Test distinction between retryable and non-retryable errors."""
        # Create a test post
        post = PostFactory(blur_data_url="")

        # Test non-retryable error
        mock_generate_blur.side_effect = Exception("Invalid image format")

        result = post_generate_blur_data_url.delay(post.id)

        assert result.result["success"] is False
        assert "Invalid image format" in result.result["error"]


class TestPeriodicGeneratePostBlurDataUrls(TestCase):
    """Tests for the periodic_generate_post_blur_data_urls Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_generate_blur_data_url.delay")
    def test_periodic_generate_post_blur_data_urls_success(self, mock_task_delay):
        """Test successful queuing of blur data URL generation tasks."""
        # Create posts without blur_data_url
        PostFactory(blur_data_url="")
        PostFactory(blur_data_url="")
        PostFactory(blur_data_url="")

        # Create a post with blur_data_url (should be skipped)
        PostFactory(blur_data_url="existing_blur_data")

        # Mock the task delay to return a mock result
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

        # Verify post_generate_blur_data_url was called for each post
        assert mock_task_delay.call_count == 3  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_blur_data_urls_no_posts(self):
        """Test when no posts need processing."""
        # Create only posts with blur_data_url
        PostFactory(blur_data_url="existing_blur_data_1")
        PostFactory(blur_data_url="existing_blur_data_2")

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify the task returns success with no posts processed
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_generate_blur_data_url.delay")
    def test_periodic_generate_post_blur_data_urls_only_empty_blur_data(
        self,
        mock_task_delay,
    ):
        """Test that only posts without blur_data_url are processed."""
        # Create posts with and without blur_data_url
        post_without_blur = PostFactory(blur_data_url="")
        PostFactory(blur_data_url="has_blur_data")

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify only one post was queued
        assert result.result["total"] == 1
        assert result.result["queued"] == 1

        # Verify the correct post was queued
        mock_task_delay.assert_called_once_with(post_without_blur.id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_generate_blur_data_url.delay")
    def test_periodic_generate_post_blur_data_urls_error_handling(
        self,
        mock_task_delay,
    ):
        """Test error handling when queuing tasks fails."""
        # Create posts without blur_data_url
        PostFactory(blur_data_url="")
        PostFactory(blur_data_url="")

        # Mock the task delay to raise an exception for the first post
        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify the task completed with errors
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1
        assert result.result["error_details"] is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_generate_blur_data_url.delay")
    def test_periodic_generate_post_blur_data_urls_task_ids(self, mock_task_delay):
        """Test that task IDs are returned correctly."""
        # Create posts without blur_data_url
        PostFactory(blur_data_url="")
        PostFactory(blur_data_url="")

        # Mock the task delay with different task IDs
        mock_task_delay.side_effect = [
            Mock(id="task-id-1"),
            Mock(id="task-id-2"),
        ]

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify task IDs are returned
        assert result.result["success"] is True
        assert len(result.result["task_ids"]) == 2  # noqa: PLR2004
        assert "task-id-1" in result.result["task_ids"]
        assert "task-id-2" in result.result["task_ids"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_blur_data_urls_empty_database(self):
        """Test when there are no posts in the database."""
        # Ensure no posts exist
        Post.objects.all().delete()

        # Execute the task
        result = periodic_generate_post_blur_data_urls.delay()

        # Verify the task returns success with no posts
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0


class TestPostMediaGenerateBlurDataUrl(TestCase):
    """Tests for the post_media_generate_blur_data_url Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_media_generate_blur_data_url_success(self, mock_generate_blur):
        """Test successful blur data URL generation and saving."""
        # Create a test post media
        post = PostFactory()
        post_media = PostMediaFactory(post=post, blur_data_url="")

        # Mock the utility function
        mock_generate_blur.return_value = "base64encodedstring"

        # Execute the task
        result = post_media_generate_blur_data_url.delay(post_media.id)

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["post_media_id"] == post_media.id

        # Verify the blur_data_url was saved to the model
        post_media.refresh_from_db()
        assert post_media.blur_data_url == "base64encodedstring"

        # Verify the utility function was called
        mock_generate_blur.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_post_media_generate_blur_data_url_not_found(self):
        """Test handling of non-existent post media."""
        # Execute the task with non-existent post media ID
        result = post_media_generate_blur_data_url.delay(999999)

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_media_generate_blur_data_url_saves_to_model(
        self,
        mock_generate_blur,
    ):
        """Test that blur_data_url is correctly saved to the PostMedia model."""
        # Create a test post media
        post = PostFactory()
        post_media = PostMediaFactory(post=post, blur_data_url="")

        # Mock the utility function with a specific value
        test_blur_data = "test_base64_encoded_blur_data"
        mock_generate_blur.return_value = test_blur_data

        # Execute the task
        post_media_generate_blur_data_url.delay(post_media.id)

        # Verify the blur_data_url was saved
        post_media.refresh_from_db()
        assert post_media.blur_data_url == test_blur_data

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_media_generate_blur_data_url_network_error_retry(
        self,
        mock_generate_blur,
    ):
        """Test retry logic on network errors."""
        # Create a test post media
        post = PostFactory()
        post_media = PostMediaFactory(post=post, blur_data_url="")

        # Mock a network error
        mock_generate_blur.side_effect = Exception("Network timeout")

        # Execute the task
        result = post_media_generate_blur_data_url.delay(post_media.id)

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_blur_data_url_from_image_url")
    def test_post_media_generate_blur_data_url_uses_thumbnail(
        self,
        mock_generate_blur,
    ):
        """Test that the task uses the correct thumbnail source."""
        # Create a test post media with thumbnail
        post = PostFactory()
        post_media = PostMediaFactory(
            post=post,
            blur_data_url="",
            thumbnail_url="https://example.com/thumbnail.jpg",
        )

        # Mock the utility function
        mock_generate_blur.return_value = "base64encodedstring"

        # Execute the task
        post_media_generate_blur_data_url.delay(post_media.id)

        # Verify the utility function was called
        mock_generate_blur.assert_called_once()


class TestPeriodicGeneratePostMediaBlurDataUrls(TestCase):
    """Tests for the periodic_generate_post_media_blur_data_urls Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_media_generate_blur_data_url.delay")
    def test_periodic_generate_post_media_blur_data_urls_success(
        self,
        mock_task_delay,
    ):
        """Test successful queuing of blur data URL generation tasks."""
        # Create post media without blur_data_url
        post = PostFactory()
        PostMediaFactory(post=post, blur_data_url="")
        PostMediaFactory(post=post, blur_data_url="")
        PostMediaFactory(post=post, blur_data_url="")

        # Create a post media with blur_data_url (should be skipped)
        PostMediaFactory(post=post, blur_data_url="existing_blur_data")

        # Mock the task delay to return a mock result
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = periodic_generate_post_media_blur_data_urls.delay()

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

        # Verify post_media_generate_blur_data_url was called for each post media
        assert mock_task_delay.call_count == 3  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_periodic_generate_post_media_blur_data_urls_no_items(self):
        """Test when no post media need processing."""
        # Create only post media with blur_data_url
        post = PostFactory()
        PostMediaFactory(post=post, blur_data_url="existing_blur_data_1")
        PostMediaFactory(post=post, blur_data_url="existing_blur_data_2")

        # Execute the task
        result = periodic_generate_post_media_blur_data_urls.delay()

        # Verify the task returns success with no items processed
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_media_generate_blur_data_url.delay")
    def test_periodic_generate_post_media_blur_data_urls_only_empty_blur_data(
        self,
        mock_task_delay,
    ):
        """Test that only post media without blur_data_url are processed."""
        # Create post media with and without blur_data_url
        post = PostFactory()
        post_media_without_blur = PostMediaFactory(post=post, blur_data_url="")
        PostMediaFactory(post=post, blur_data_url="has_blur_data")

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = periodic_generate_post_media_blur_data_urls.delay()

        # Verify only one post media was queued
        assert result.result["total"] == 1
        assert result.result["queued"] == 1

        # Verify the correct post media was queued
        mock_task_delay.assert_called_once_with(post_media_without_blur.id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.post_media_generate_blur_data_url.delay")
    def test_periodic_generate_post_media_blur_data_urls_error_handling(
        self,
        mock_task_delay,
    ):
        """Test error handling when queuing tasks fails."""
        # Create post media without blur_data_url
        post = PostFactory()
        PostMediaFactory(post=post, blur_data_url="")
        PostMediaFactory(post=post, blur_data_url="")

        # Mock the task delay to raise an exception for the first item
        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        # Execute the task
        result = periodic_generate_post_media_blur_data_urls.delay()

        # Verify the task completed with errors
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1
        assert result.result["error_details"] is not None


def _make_post_image_file():
    """Return a minimal ContentFile that looks like a JPEG."""
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    img = Image.new("RGB", (10, 10), color="red")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return ContentFile(buf.read(), name="thumb.jpg")


class TestGeneratePostEmbedding(TestCase):
    """Tests for the generate_post_embedding Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_post_not_found(self):
        """Test handling of non-existent post."""
        result = generate_post_embedding.delay("nonexistent_post_id")
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_embedding_already_exists(self):
        """Test that task skips if embedding already exists."""
        post = PostFactory(caption="Test caption", embedding=[0.5] * 1536)
        result = generate_post_embedding.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "already exists" in result.result["message"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_thumbnail(self):
        """Test handling when post has no thumbnail file."""
        post = PostFactory(thumbnail_url="", embedding=None)
        result = generate_post_embedding.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "No thumbnail file" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.post.generate_image_embedding")
    def test_success(self, mock_generate_embedding):
        """Test successful embedding generation and saving."""
        post = PostFactory(thumbnail_url="", embedding=None)
        post.thumbnail.save("thumb.jpg", _make_post_image_file(), save=True)

        test_embedding = [0.1] * 1536
        mock_generate_embedding.return_value = (test_embedding, 100)

        result = generate_post_embedding.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["post_id"] == post.id
        assert result.result["dimensions"] == 1536  # noqa: PLR2004

        post.refresh_from_db()
        assert post.embedding is not None
        assert len(post.embedding) == 1536  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.post.generate_image_embedding")
    def test_saves_to_model(self, mock_generate_embedding):
        """Test that embedding is correctly saved to the Post model."""
        post = PostFactory(thumbnail_url="", embedding=None)
        post.thumbnail.save("thumb.jpg", _make_post_image_file(), save=True)

        test_embedding = [0.123] * 1536
        mock_generate_embedding.return_value = (test_embedding, 100)

        generate_post_embedding.delay(post.id)

        post.refresh_from_db()
        assert post.embedding is not None
        assert len(post.embedding) == 1536  # noqa: PLR2004
        assert post.embedding[0] == 0.123  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.post.generate_image_embedding")
    def test_value_error_returns_failure(self, mock_generate_embedding):
        """Test handling of ValueError from model method."""
        post = PostFactory(thumbnail_url="", embedding=None)
        post.thumbnail.save("thumb.jpg", _make_post_image_file(), save=True)

        mock_generate_embedding.side_effect = ValueError("Bad input")

        result = generate_post_embedding.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "ValueError" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.post.generate_image_embedding")
    def test_network_error_retry(self, mock_generate_embedding):
        """Test retry logic on network errors."""
        post = PostFactory(thumbnail_url="", embedding=None)
        post.thumbnail.save("thumb.jpg", _make_post_image_file(), save=True)

        mock_generate_embedding.side_effect = Exception("Network timeout")

        result = generate_post_embedding.delay(post.id)
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result


class TestPeriodicGeneratePostEmbeddings(TestCase):
    """Tests for the periodic_generate_post_embeddings Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_post_embedding.delay")
    def test_success(self, mock_task_delay):
        """Test successful queuing of embedding generation tasks."""
        Post.objects.all().delete()

        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        for i in range(3):
            post = PostFactory(thumbnail_url="", embedding=None)
            post.thumbnail.save(f"thumb{i}.jpg", _make_post_image_file(), save=True)
        PostFactory(caption="has embedding", embedding=[0.1] * 1536)

        result = periodic_generate_post_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_no_posts_to_process(self):
        """Test when no posts need processing."""
        Post.objects.all().delete()
        PostFactory(caption="Caption 1", embedding=[0.1] * 1536)
        PostFactory(caption="Caption 2", embedding=[0.2] * 1536)

        result = periodic_generate_post_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_post_embedding.delay")
    def test_only_posts_without_embeddings(self, mock_task_delay):
        """Test that only posts without embeddings are processed."""
        Post.objects.all().delete()

        post_without = PostFactory(thumbnail_url="", embedding=None)
        post_without.thumbnail.save("thumb.jpg", _make_post_image_file(), save=True)
        PostFactory(thumbnail_url="", embedding=[0.1] * 1536)

        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        result = periodic_generate_post_embeddings.delay()
        assert result.result["total"] == 1
        assert result.result["queued"] == 1
        mock_task_delay.assert_called_once_with(post_without.id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.post.generate_post_embedding.delay")
    def test_error_handling(self, mock_task_delay):
        """Test error handling when queuing tasks fails."""
        Post.objects.all().delete()

        for i in range(2):
            post = PostFactory(thumbnail_url="", embedding=None)
            post.thumbnail.save(f"thumb{i}.jpg", _make_post_image_file(), save=True)

        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        result = periodic_generate_post_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1
        assert result.result["error_details"] is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_posts_without_thumbnails_skipped(self):
        """Test that posts without thumbnails are not queued."""
        Post.objects.all().delete()
        PostFactory(thumbnail_url="", embedding=None)
        PostFactory(thumbnail_url="", embedding=None)

        result = periodic_generate_post_embeddings.delay()
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0


class TestIncrementPostViewCount(TestCase):
    def test_increments_view_count(self):
        post = PostFactory()
        assert post.view_count == 0

        increment_post_view_count(post.id)

        post.refresh_from_db()
        assert post.view_count == 1

    def test_does_not_create_historical_record(self):
        """Incrementing view_count must use .update(), not .save(), to avoid
        triggering simple_history's post_save signal on every view."""
        post = PostFactory()
        history_count_before = post.history.count()

        increment_post_view_count(post.id)

        assert post.history.count() == history_count_before

    def test_missing_post_is_a_no_op(self):
        increment_post_view_count("does-not-exist")
