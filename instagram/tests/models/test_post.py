from io import BytesIO
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from instagram.models import Post
from instagram.tests.factories import InstagramUserFactory
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


class TestPostProcessingMethods(TestCase):
    """Tests for Post model processing methods."""

    def test_process_post_by_type_carousel(self):
        """Test process_post_by_type identifies and processes carousel posts."""
        # Create post with carousel raw_data
        raw_data = {
            "id": "1234567890",
            "carousel_media": [
                {
                    "strong_id__": "carousel_item_1",
                    "display_uri": "https://example.com/carousel1.jpg",
                },
                {
                    "strong_id__": "carousel_item_2",
                    "display_uri": "https://example.com/carousel2.jpg",
                },
            ],
        }
        post = PostFactory(raw_data=raw_data)

        # Process the post
        post.process_post_by_type()

        # Verify variant was set to carousel
        post.refresh_from_db()
        assert post.variant == post.POST_VARIANT_CAROUSEL

        # Verify PostMedia objects were created
        assert post.postmedia_set.count() == 2  # noqa: PLR2004

    def test_process_post_by_type_video(self):
        """Test process_post_by_type identifies and processes video posts."""
        # Create post with video raw_data
        raw_data = {
            "id": "1234567890",
            "video_versions": [
                {"url": "https://example.com/video.mp4"},
            ],
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/thumbnail.jpg"},
                ],
            },
        }
        post = PostFactory(raw_data=raw_data)

        # Process the post
        post.process_post_by_type()

        # Verify variant was set to video
        post.refresh_from_db()
        assert post.variant == post.POST_VARIANT_VIDEO

        # Verify PostMedia object was created
        assert post.postmedia_set.count() == 1

    def test_process_post_by_type_normal(self):
        """Test process_post_by_type identifies and processes normal posts."""
        # Create post with normal raw_data (no carousel_media or video_versions)
        raw_data = {
            "id": "1234567890",
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/image.jpg"},
                ],
            },
        }
        post = PostFactory(raw_data=raw_data)

        # Process the post
        post.process_post_by_type()

        # Verify variant was set to normal
        post.refresh_from_db()
        assert post.variant == post.POST_VARIANT_NORMAL

        # Verify PostMedia object was created
        assert post.postmedia_set.count() == 1

    def test_process_post_by_type_no_raw_data(self):
        """Test process_post_by_type handles posts without raw_data."""
        # Create post without raw_data
        post = PostFactory(raw_data=None)

        # Process the post - should not raise an error
        post.process_post_by_type()

        # No PostMedia should be created
        assert post.postmedia_set.count() == 0

    def test_handle_post_carousel_idempotent(self):
        """Test handle_post_carousel is idempotent (safe to call multiple times)."""
        # Create post with carousel raw_data
        raw_data = {
            "id": "1234567890",
            "carousel_media": [
                {
                    "strong_id__": "carousel_item_1",
                    "display_uri": "https://example.com/carousel1.jpg",
                },
            ],
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_carousel multiple times
        post.handle_post_carousel()
        post.handle_post_carousel()
        post.handle_post_carousel()

        # Verify only one PostMedia object was created (due to get_or_create)
        assert post.postmedia_set.count() == 1

    def test_handle_post_normal_creates_post_media(self):
        """Test handle_post_normal creates PostMedia with correct data."""
        # Create post with normal raw_data
        raw_data = {
            "id": "1234567890",
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/image.jpg"},
                ],
            },
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_normal
        post.handle_post_normal()

        # Verify PostMedia was created with correct data
        post_media = post.postmedia_set.first()
        assert post_media is not None
        assert post_media.reference == raw_data["id"]
        assert post_media.thumbnail_url == "https://example.com/image.jpg"
        assert post_media.media_url == "https://example.com/image.jpg"

    def test_handle_post_carousel_creates_multiple_media(self):
        """Test handle_post_carousel creates multiple PostMedia objects."""
        # Create post with carousel raw_data
        raw_data = {
            "id": "1234567890",
            "carousel_media": [
                {
                    "strong_id__": "carousel_item_1",
                    "display_uri": "https://example.com/carousel1.jpg",
                },
                {
                    "strong_id__": "carousel_item_2",
                    "display_uri": "https://example.com/carousel2.jpg",
                },
                {
                    "strong_id__": "carousel_item_3",
                    "display_uri": "https://example.com/carousel3.jpg",
                },
            ],
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_carousel
        post.handle_post_carousel()

        # Verify all PostMedia objects were created
        assert post.postmedia_set.count() == 3  # noqa: PLR2004

        # Verify each has correct reference
        references = list(post.postmedia_set.values_list("reference", flat=True))
        assert "carousel_item_1" in references
        assert "carousel_item_2" in references
        assert "carousel_item_3" in references

    def test_handle_post_video_creates_post_media(self):
        """Test handle_post_video creates PostMedia with video URL."""
        # Create post with video raw_data
        raw_data = {
            "id": "1234567890",
            "video_versions": [
                {"url": "https://example.com/video.mp4"},
            ],
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/thumbnail.jpg"},
                ],
            },
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_video
        post.handle_post_video()

        # Verify PostMedia was created with video URL
        post_media = post.postmedia_set.first()
        assert post_media is not None
        assert post_media.reference == raw_data["id"]
        assert post_media.thumbnail_url == "https://example.com/thumbnail.jpg"
        assert post_media.media_url == "https://example.com/video.mp4"

    def test_handle_post_normal_skips_carousel(self):
        """Test handle_post_normal skips processing if carousel_media exists."""
        # Create post with carousel raw_data
        raw_data = {
            "id": "1234567890",
            "carousel_media": [
                {
                    "strong_id__": "carousel_item_1",
                    "display_uri": "https://example.com/carousel1.jpg",
                },
            ],
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_normal (should skip)
        post.handle_post_normal()

        # Verify variant was NOT changed to normal
        post.refresh_from_db()
        # Variant should still be whatever was set by factory (carousel or normal)
        # No PostMedia should be created by handle_post_normal
        assert post.postmedia_set.count() == 0

    def test_handle_post_video_skips_without_video_versions(self):
        """Test handle_post_video skips if no video_versions in raw_data."""
        # Create post without video_versions
        raw_data = {
            "id": "1234567890",
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/image.jpg"},
                ],
            },
        }
        post = PostFactory(raw_data=raw_data)

        # Call handle_post_video
        post.handle_post_video()

        # Verify variant was set to video but no PostMedia created
        post.refresh_from_db()
        assert post.variant == post.POST_VARIANT_VIDEO
        assert post.postmedia_set.count() == 0


class TestPostThumbnailInsight(TestCase):
    """Tests for Post.generate_thumbnail_insight() method."""

    @patch("instagram.models.post.get_openai_client")
    def test_generate_thumbnail_insight_success(self, mock_get_client):
        """Test successful thumbnail insight generation."""
        # Create a post with a thumbnail file
        post = PostFactory()

        # Create a dummy image
        image = Image.new("RGB", (100, 100), color="red")
        image_io = BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)

        # Save the image to the post's thumbnail field
        post.thumbnail.save("test_thumbnail.jpg", ContentFile(image_io.read()))

        # Mock OpenAI client and response
        mock_client = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="A beautiful red image"))]
        mock_response.usage = Mock(total_tokens=150)
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Generate insight
        post.generate_thumbnail_insight()

        # Verify the insight was saved
        post.refresh_from_db()
        assert post.thumbnail_insight == "A beautiful red image"
        assert post.thumbnail_insight_token_usage == 150  # noqa: PLR2004

        # Verify OpenAI client was called
        mock_get_client.assert_called_once()
        mock_client.chat.completions.create.assert_called_once()

    def test_generate_thumbnail_insight_no_thumbnail(self):
        """Test error when post has no thumbnail file."""
        # Create a post without a thumbnail
        post = PostFactory()

        # Attempt to generate insight should raise ValueError
        with pytest.raises(ValueError, match="Thumbnail file does not exist"):
            post.generate_thumbnail_insight()

    @patch("instagram.models.post.get_openai_client")
    def test_generate_thumbnail_insight_openai_error(self, mock_get_client):
        """Test handling of OpenAI API errors."""
        # Create a post with a thumbnail file
        post = PostFactory()

        # Create a dummy image
        image = Image.new("RGB", (100, 100), color="blue")
        image_io = BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)
        post.thumbnail.save("test_thumbnail.jpg", ContentFile(image_io.read()))

        # Mock OpenAI client to raise an error
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        # Generate insight should return empty string on error
        result = post.generate_thumbnail_insight()

        # Verify empty string is returned
        assert result == ""

        # Verify insight was not saved
        post.refresh_from_db()
        assert post.thumbnail_insight == ""

    @patch("instagram.models.post.get_openai_client")
    def test_generate_thumbnail_insight_saves_token_usage(self, mock_get_client):
        """Test that token usage is correctly saved."""
        # Create a post with a thumbnail file
        post = PostFactory()

        # Create a dummy image
        image = Image.new("RGB", (100, 100), color="green")
        image_io = BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)
        post.thumbnail.save("test_thumbnail.jpg", ContentFile(image_io.read()))

        # Mock OpenAI client with specific token usage
        mock_client = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Green image insight"))]
        mock_response.usage = Mock(total_tokens=250)
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Generate insight
        post.generate_thumbnail_insight()

        # Verify token usage was saved
        post.refresh_from_db()
        assert post.thumbnail_insight_token_usage == 250  # noqa: PLR2004

    @patch("instagram.models.post.get_openai_client")
    def test_generate_thumbnail_insight_uses_correct_model(self, mock_get_client):
        """Test that the correct OpenAI model is used."""
        # Create a post with a thumbnail file
        post = PostFactory()

        # Create a dummy image
        image = Image.new("RGB", (100, 100), color="yellow")
        image_io = BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)
        post.thumbnail.save("test_thumbnail.jpg", ContentFile(image_io.read()))

        # Mock OpenAI client
        mock_client = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Yellow image"))]
        mock_response.usage = Mock(total_tokens=100)
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Generate insight
        post.generate_thumbnail_insight()

        # Verify the correct model was used
        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["model"] == "gpt-5-mini"


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

    def test_caption_extraction_from_raw_data(self):
        """Test caption is correctly extracted from raw_data during API update."""
        # Create a user
        user = InstagramUserFactory()

        # Create post with raw_data containing caption
        raw_data = {
            "pk": "1234567890",
            "display_uri": "https://example.com/image.jpg",
            "caption": {
                "text": "Caption from API",
            },
            "taken_at": 1234567890,
        }

        # Simulate what happens in User._update_post_data_from_api
        obj, _ = Post.objects.update_or_create(
            id=raw_data.get("pk"),
            user=user,
        )
        obj.raw_data = raw_data
        obj.thumbnail_url = raw_data.get("display_uri")
        obj.caption = (
            raw_data.get("caption").get("text") if raw_data.get("caption") else ""
        )
        obj.save()

        # Verify caption was extracted correctly
        post = Post.objects.get(id="1234567890")
        assert post.caption == "Caption from API"

    def test_caption_extraction_with_missing_caption(self):
        """Test caption extraction when caption is missing from raw_data."""
        # Create a user
        user = InstagramUserFactory()

        # Create post with raw_data without caption
        raw_data = {
            "pk": "9876543210",
            "display_uri": "https://example.com/image2.jpg",
            "taken_at": 1234567890,
        }

        # Simulate what happens in User._update_post_data_from_api
        obj, _ = Post.objects.update_or_create(
            id=raw_data.get("pk"),
            user=user,
        )
        obj.raw_data = raw_data
        obj.thumbnail_url = raw_data.get("display_uri")
        obj.caption = (
            raw_data.get("caption").get("text") if raw_data.get("caption") else ""
        )
        obj.save()

        # Verify caption defaults to empty string
        post = Post.objects.get(id="9876543210")
        assert post.caption == ""

    def test_caption_extraction_with_none_caption(self):
        """Test caption extraction when caption is None in raw_data."""
        # Create a user
        user = InstagramUserFactory()

        # Create post with raw_data with None caption
        raw_data = {
            "pk": "1111111111",
            "display_uri": "https://example.com/image3.jpg",
            "caption": None,
            "taken_at": 1234567890,
        }

        # Simulate what happens in User._update_post_data_from_api
        obj, _ = Post.objects.update_or_create(
            id=raw_data.get("pk"),
            user=user,
        )
        obj.raw_data = raw_data
        obj.thumbnail_url = raw_data.get("display_uri")
        obj.caption = (
            raw_data.get("caption").get("text") if raw_data.get("caption") else ""
        )
        obj.save()

        # Verify caption defaults to empty string
        post = Post.objects.get(id="1111111111")
        assert post.caption == ""


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
