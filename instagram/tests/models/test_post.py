from io import BytesIO
from unittest.mock import patch

from django.core.files.storage import InMemoryStorage
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


class TestPostDownloadThumbnail(TestCase):
    """Tests for the Post.download_thumbnail method."""

    def setUp(self):
        self.storage = InMemoryStorage()
        patcher = patch.object(
            Post._meta.get_field("thumbnail"),  # noqa: SLF001
            "storage",
            self.storage,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("instagram.models.post.download_file_from_url")
    def test_downloads_and_saves_name(self, mock_download):
        """The file is stored and its name written to the row without history."""
        mock_download.return_value = (b"jpeg-bytes", "jpg")
        post = PostFactory(thumbnail_url="https://cdn.example.com/a.jpg")
        history_count = post.history.count()

        saved_name = post.download_thumbnail()

        assert saved_name.endswith(".jpg")
        assert Post.objects.get(pk=post.pk).thumbnail.name == saved_name
        assert post.history.count() == history_count
        mock_download.assert_called_once_with("https://cdn.example.com/a.jpg")

    @patch("instagram.models.post.download_file_from_url")
    def test_skips_without_url_or_on_failure(self, mock_download):
        """Nothing is saved when the URL is empty or the download fails."""
        post = PostFactory(thumbnail_url="")
        assert post.download_thumbnail() is None
        mock_download.assert_not_called()

        mock_download.return_value = (None, None)
        post.thumbnail_url = "https://cdn.example.com/a.jpg"
        assert post.download_thumbnail() is None
        assert not Post.objects.get(pk=post.pk).thumbnail

    @patch("instagram.models.post.download_file_from_url")
    def test_skips_when_thumbnail_exists(self, mock_download):
        """A post that already has a thumbnail is not downloaded again."""
        post = PostFactory()
        post.thumbnail.name = "posts/x/existing.jpg"

        assert post.download_thumbnail() is None
        mock_download.assert_not_called()

    @patch("instagram.models.post.download_file_from_url")
    def test_loser_of_race_deletes_its_file(self, mock_download):
        """If another worker saved a thumbnail first, the new file is removed."""
        mock_download.return_value = (b"jpeg-bytes", "jpg")
        post = PostFactory()
        Post.objects.filter(pk=post.pk).update(thumbnail="posts/x/winner.jpg")

        assert post.download_thumbnail() is None
        assert Post.objects.get(pk=post.pk).thumbnail.name == "posts/x/winner.jpg"
        _, files = self.storage.listdir(f"posts/{post.user.username}")
        assert files == []
