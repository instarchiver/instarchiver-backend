from io import BytesIO
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory


class TestPostModel(TestCase):
    """Tests for the Post model methods."""

    def test_post_creation(self):
        """Test that a Post instance can be created successfully."""
        post = PostFactory()

        assert post.id is not None
        assert post.user is not None
        assert post.variant in [post.POST_VARIANT_NORMAL, post.POST_VARIANT_CAROUSEL]
        assert post.thumbnail_url is not None
        assert post.created_at is not None
        assert post.updated_at is not None

    def test_post_str_representation(self):
        """Test the string representation of a Post instance."""
        post = PostFactory()
        expected_str = f"{post.user.username} - {post.id}"

        assert str(post) == expected_str

    def test_post_user_relationship(self):
        """Test that Post has a valid relationship with User."""
        post = PostFactory()

        assert post.user.username is not None
        assert post.user.instagram_id is not None

    @patch("instagram.tasks.post_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_queues_task(self, mock_task_delay):
        """Test that generate_blur_data_url_task queues a Celery task."""
        # Create a test post
        post = PostFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method
        post.generate_blur_data_url_task()

        # Verify the task was queued
        mock_task_delay.assert_called_once()

    @patch("instagram.tasks.post_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_passes_post_id(
        self,
        mock_task_delay,
    ):
        """Test that generate_blur_data_url_task passes correct post id."""
        # Create a test post
        post = PostFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method
        post.generate_blur_data_url_task()

        # Verify the task was called with the correct post id
        mock_task_delay.assert_called_once_with(post.id)

    @patch("instagram.tasks.post_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_multiple_calls(
        self,
        mock_task_delay,
    ):
        """Test multiple calls queue separate tasks."""
        # Create test posts
        post1 = PostFactory()
        post2 = PostFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method on both posts
        post1.generate_blur_data_url_task()
        post2.generate_blur_data_url_task()

        # Verify the task was queued twice with different post ids
        assert mock_task_delay.call_count == 2  # noqa: PLR2004
        mock_task_delay.assert_any_call(post1.id)
        mock_task_delay.assert_any_call(post2.id)


class TestPostMediaModel(TestCase):
    """Tests for the PostMedia model."""

    def test_post_media_creation(self):
        """Test that a PostMedia instance can be created successfully."""
        post_media = PostMediaFactory()

        assert post_media.id is not None
        assert post_media.post is not None
        assert post_media.thumbnail_url is not None
        assert post_media.media_url is not None
        assert post_media.created_at is not None
        assert post_media.updated_at is not None

    def test_post_media_str_representation(self):
        """Test the string representation of a PostMedia instance."""
        post_media = PostMediaFactory()
        expected_str = f"{post_media.post.user.username} - {post_media.post.id}"

        assert str(post_media) == expected_str

    def test_post_media_post_relationship(self):
        """Test that PostMedia has a valid relationship with Post."""
        post_media = PostMediaFactory()

        assert post_media.post.id is not None
        assert post_media.post.user is not None
        assert post_media.post.variant is not None

    @patch("instagram.tasks.post_media_generate_blur_data_url.delay")
    def test_generate_blur_data_url_task_queues_task(self, mock_task_delay):
        """Test that generate_blur_data_url_task queues a Celery task."""
        # Create a test post media
        post_media = PostMediaFactory()

        # Mock the task delay
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Call the method
        post_media.generate_blur_data_url_task()

        # Verify the task was queued
        mock_task_delay.assert_called_once_with(post_media.id)


class TestPostCaption(TestCase):
    """Tests for Post model caption field."""

    def test_post_caption_saved_from_factory(self):
        """Test that caption can be saved when creating a Post."""
        # Create post with caption
        caption_text = "This is a test caption for my post"
        post = PostFactory(caption=caption_text)

        # Verify caption was saved
        assert post.caption == caption_text

        # Verify it persists in database
        post.refresh_from_db()
        assert post.caption == caption_text

    def test_post_caption_accepts_empty_string(self):
        """Test that caption field accepts empty strings."""
        # Create post with empty caption
        post = PostFactory(caption="")

        # Verify empty caption was saved
        assert post.caption == ""

        # Verify it persists in database
        post.refresh_from_db()
        assert post.caption == ""

    def test_post_caption_accepts_long_text(self):
        """Test that caption field can handle long text."""
        # Create a long caption (Instagram allows up to 2,200 characters)
        long_caption = "A" * 2200

        # Create post with long caption
        post = PostFactory(caption=long_caption)

        # Verify long caption was saved
        assert post.caption == long_caption
        assert len(post.caption) == 2200  # noqa: PLR2004

        # Verify it persists in database
        post.refresh_from_db()
        assert post.caption == long_caption

    def test_post_caption_with_special_characters(self):
        """Test that caption field handles special characters and emojis."""
        # Create caption with special characters and emojis
        special_caption = "Hello! 👋 This is a #test with @mentions & emojis 🎉🔥"

        # Create post with special caption
        post = PostFactory(caption=special_caption)

        # Verify caption was saved correctly
        assert post.caption == special_caption

        # Verify it persists in database
        post.refresh_from_db()
        assert post.caption == special_caption

    def test_post_caption_with_newlines(self):
        """Test that caption field preserves newlines and formatting."""
        # Create caption with newlines
        multiline_caption = "Line 1\nLine 2\n\nLine 3 with double newline"

        # Create post with multiline caption
        post = PostFactory(caption=multiline_caption)

        # Verify caption preserves newlines
        assert post.caption == multiline_caption
        assert "\n" in post.caption

        # Verify it persists in database
        post.refresh_from_db()
        assert post.caption == multiline_caption


def _make_image_file():
    """Return a minimal SimpleUploadedFile that looks like a JPEG."""
    img = Image.new("RGB", (10, 10), color="red")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile("thumb.jpg", buf.read(), content_type="image/jpeg")


class TestPostModerateContent(TestCase):
    """Tests for Post.moderate_content() method."""

    def test_moderate_content_raises_error_without_thumbnail(self):
        """Test that moderate_content raises ValueError when no thumbnail exists."""
        post = PostFactory(thumbnail_url="", raw_data=None)

        with pytest.raises(ValueError, match="Thumbnail is required"):
            post.moderate_content()

    @patch("instagram.models.post.moderate_image_content")
    def test_moderate_content_success_flagged(self, mock_moderate):
        """Test moderate_content saves fields when content is flagged."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        post.thumbnail.save("thumb.jpg", _make_image_file(), save=True)

        mock_moderate.return_value = {
            "flagged": True,
            "categories": {"violence": True},
        }

        post.moderate_content()

        post.refresh_from_db()
        assert post.is_flagged is True
        assert post.moderation_result == {
            "flagged": True,
            "categories": {"violence": True},
        }
        assert post.moderated_at is not None

    @patch("instagram.models.post.moderate_image_content")
    def test_moderate_content_success_not_flagged(self, mock_moderate):
        """Test moderate_content saves is_flagged=False when content is clean."""
        post = PostFactory(thumbnail_url="", raw_data=None)
        post.thumbnail.save("thumb.jpg", _make_image_file(), save=True)

        mock_moderate.return_value = {"is_flagged": False, "categories": {}}

        post.moderate_content()

        post.refresh_from_db()
        assert post.is_flagged is False
        assert post.moderated_at is not None
